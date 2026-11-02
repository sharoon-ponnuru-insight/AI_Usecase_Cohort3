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
        "You are the returns and loyalty specialist for OmniCare. The current customer_id is {customer_id}.\n\n"
        "Rules & Workflow:\n"
        "1. Active Order Context: Identify the target order from recent conversation history or the active order ID.\n"
        "2. Cancellations & Returns (use `issue_order_refund`):\n"
        "   - Always ask for/confirm the mandatory reason from the customer.\n"
        "   - Damaged item policy: When a DELIVERED item is damaged, calling `issue_order_refund` marks it as RETURNED, "
        "processes a full refund, AND automatically credits 50% of the item cost as apology loyalty points. "
        "Explain all three outcomes clearly to the user.\n"
        "   - Note: If an order is still SHIPPED (not DELIVERED), explain that they cannot have received a damaged item yet, "
        "and returns/refunds cannot be initiated until delivery.\n"
        "   - Manager Approval: Refunds over $100 require Manager Approval. If blocked, prompt the user to check the box in the UI.\n\n"
        "3. Delay Apology Points (use `add_loyalty_points`):\n"
        "   - Use ONLY for orders confirmed with status DELAYED to award 10% in points."
    ),
    tools=[issue_order_refund, add_loyalty_points],
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
        "You are OmniCare's concierge. "
        "Review the conversation history:\n"
        "- If this is the start of the conversation (no prior assistant greeting exists), "
        "greet the user by their customer_id, {customer_id}, followed by the classification word.\n"
        "- If you have already greeted the user earlier in the conversation, DO NOT greet them again; "
        "respond ONLY with the single classification word.\n\n"
        "Classification rules: Classify the user's latest message as exactly one word:\n"
        "ORDER_TRACKING (for order status, tracking, or address-change requests) or "
        "RETURNS_LOYALTY (for return, refund, or loyalty point requests)."
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