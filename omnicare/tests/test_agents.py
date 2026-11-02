"""Tests for omnicare/agents.py.

These tests avoid making real LLM calls: they only exercise agent/workflow
*construction* (importing the module already builds every Agent/Workflow
object with no network I/O) plus the pure-Python helper functions
(`_with_history`, the routing logic inside `route_to_specialist`).
"""

from __future__ import annotations

from omnicare import agents
from omnicare.tests.conftest import FakeReadonlyContext


def test_agents_are_constructed_with_expected_names():
    assert agents.concierge_router_agent.name == "concierge_router_agent"
    assert agents.order_tracking_agent.name == "order_tracking_agent"
    assert agents.returns_and_loyalty_agent.name == "returns_and_loyalty_agent"


def test_root_agent_is_a_workflow_with_compiled_graph():
    assert agents.root_agent.name == "concierge_router_agent"
    assert agents.root_agent.graph is not None


def test_specialist_agents_have_expected_tools():
    tool_names = {t.__name__ for t in agents.order_tracking_agent.tools}
    assert tool_names == {"get_order_status", "update_delivery_address"}

    tool_names = {t.__name__ for t in agents.returns_and_loyalty_agent.tools}
    assert tool_names == {"issue_order_refund", "add_loyalty_points"}


def test_route_to_specialist_routes_refund_requests():
    event = agents.route_to_specialist._unwrapped_func("I want a REFUND for my order")
    assert event.actions.route == "RETURNS_LOYALTY"


def test_route_to_specialist_routes_return_requests():
    event = agents.route_to_specialist._unwrapped_func("I'd like to return this")
    assert event.actions.route == "RETURNS_LOYALTY"


def test_route_to_specialist_defaults_to_order_tracking():
    event = agents.route_to_specialist._unwrapped_func("Where is my package?")
    assert event.actions.route == "ORDER_TRACKING"


def test_route_to_specialist_handles_empty_input():
    event = agents.route_to_specialist._unwrapped_func("")
    assert event.actions.route == "ORDER_TRACKING"


# --- _with_history ----------------------------------------------------------


def test_with_history_without_history_just_fills_customer_id():
    instruction_fn = agents._with_history("Hello {customer_id}, how can I help?")
    ctx = FakeReadonlyContext({"customer_id": "CUST-101"})

    result = instruction_fn(ctx)

    assert result == "Hello CUST-101, how can I help?"


def test_with_history_prepends_conversation_transcript():
    instruction_fn = agents._with_history("Hello {customer_id}.")
    ctx = FakeReadonlyContext(
        {
            "customer_id": "CUST-101",
            "conversation_history": [
                {"author": "user", "text": "Where is ORD-101?"},
                {"author": "order_tracking_agent", "text": "It is processing."},
            ],
        }
    )

    result = instruction_fn(ctx)

    assert result.startswith("Conversation so far:")
    assert "user: Where is ORD-101?" in result
    assert "order_tracking_agent: It is processing." in result
    assert result.endswith("Hello CUST-101.")


def test_with_history_defaults_customer_id_when_missing():
    instruction_fn = agents._with_history("Hello {customer_id}.")
    ctx = FakeReadonlyContext({})

    result = instruction_fn(ctx)

    assert result == "Hello unknown."
