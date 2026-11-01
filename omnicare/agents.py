"""OmniCare agents: a graph workflow that routes from the concierge router to
the right specialist sub-agent based on the user's intent.
"""

from __future__ import annotations

from google.adk import Agent, Event, Workflow
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.workflow import node

from omnicare.callbacks import (
    activity_logger_callback,
    block_test_terms_callback,
    customer_id_guard_callback,
    record_agent_response_callback,
    refund_limit_callback,
)
from omnicare.config import MODEL_NAME
from omnicare.tools import (
    add_loyalty_points,
    get_order_status,
    issue_order_refund,
    update_delivery_address,
)


def _with_history(static_instruction: str):
    """Wraps a static instruction string in a callable that prepends a short
    rolling conversation transcript from session.state, since graph-workflow
    nodes run in isolated branches and don't otherwise see prior turns.
    """

    def _instruction(ctx: ReadonlyContext) -> str:
        customer_id = ctx.state.get("customer_id", "unknown")
        filled = static_instruction.format(customer_id=customer_id)

        history = ctx.state.get("conversation_history", [])
        if not history:
            return filled

        history_text = "\n".join(f"{h['author']}: {h['text']}" for h in history)
        return f"Conversation so far:\n{history_text}\n\n{filled}"

    return _instruction

order_tracking_agent = Agent(
    name="order_tracking_agent",
    model=MODEL_NAME,
    # mode="task" is disabled/unsupported for agents used as graph-workflow
    # nodes in ADK Python v2.0.0 (it leaves the node WAITING forever, pinning
    # every subsequent user turn onto this node). single_turn completes and
    # returns control to the graph after each turn, which is what we want.
    mode="single_turn",
    rerun_on_resume=True,
    description="Checks order status/tracking and updates delivery addresses for unshipped orders.",
    instruction=_with_history(
        "You are the order tracking specialist for OmniCare. The current customer_id is "
        "{customer_id}. Use get_order_status to look up orders and update_delivery_address "
        "to change the shipping address, but only works while the order is PROCESSING. "
        "Be concise and confirm the result of every tool call to the user."
    ),
    tools=[get_order_status, update_delivery_address],
    before_tool_callback=customer_id_guard_callback,
    after_model_callback=record_agent_response_callback,
    after_tool_callback=activity_logger_callback,
)

returns_and_loyalty_agent = Agent(
    name="returns_and_loyalty_agent",
    model=MODEL_NAME,
    mode="single_turn",
    rerun_on_resume=True,
    description="Handles returns, processes refunds, and issues apology loyalty points.",
    instruction=_with_history(
        "You are the returns and loyalty specialist for OmniCare. The current customer_id is "
        "{customer_id}. Use issue_order_refund to process refunds and add_loyalty_points to "
        "issue apology points when an order was delayed or damaged. Refunds over $100 require "
        "Manager Approval; if a tool call is BLOCKED, tell the user to enable the Manager "
        "Approval checkbox in the UI."
    ),
    tools=[issue_order_refund, add_loyalty_points],
    # customer_id_guard_callback runs first and short-circuits the chain
    # (before_tool_callback list execution stops at the first non-None
    # result), so an order owned by another customer is blocked before the
    # refund-limit check ever runs.
    before_tool_callback=[customer_id_guard_callback, refund_limit_callback],
    after_model_callback=record_agent_response_callback,
    after_tool_callback=activity_logger_callback,
)

concierge_router_agent = Agent(
    name="concierge_router_agent",
    model=MODEL_NAME,
    mode="single_turn",
    rerun_on_resume=True,
    description="Greets the customer and classifies their request for routing.",
    instruction=_with_history(
        "You are OmniCare's concierge. Greet the user by their customer_id, {customer_id}. "
        "Classify the user's latest message as exactly one word: "
        "ORDER_TRACKING (for order status, tracking, or address-change requests) or "
        "RETURNS_LOYALTY (for return, refund, or loyalty point requests). "
        "Respond with a short greeting followed by that single classification word."
    ),
    before_model_callback=block_test_terms_callback,
    after_model_callback=record_agent_response_callback,
)


@node(rerun_on_resume=True)
def route_to_specialist(node_input: str) -> Event:
    """FunctionNode: routes the concierge's classification to the right specialist node."""
    text = (node_input or "").upper()
    if "RETURNS_LOYALTY" in text or "REFUND" in text or "RETURN" in text:
        return Event(route="RETURNS_LOYALTY")
    return Event(route="ORDER_TRACKING")


# Graph workflow: concierge_router_agent greets + classifies -> route_to_specialist
# dispatches to order_tracking_agent or returns_and_loyalty_agent, which in turn
# call their respective tools.
root_agent = Workflow(
    name="concierge_router_agent",
    edges=[
        ("START", concierge_router_agent, route_to_specialist),
        (
            route_to_specialist,
            {
                "ORDER_TRACKING": order_tracking_agent,
                "RETURNS_LOYALTY": returns_and_loyalty_agent,
            },
        ),
    ],
)

