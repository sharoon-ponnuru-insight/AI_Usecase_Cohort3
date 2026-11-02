"""Tests for omnicare/callbacks.py."""

from __future__ import annotations

from types import SimpleNamespace

from omnicare import callbacks, db
from omnicare.tests.conftest import FakeCallbackContext, FakeToolContext, make_llm_request, make_llm_response


# --- block_test_terms_callback (before_model_callback) --------------------


def test_block_test_terms_callback_allows_normal_message():
    ctx = FakeCallbackContext()
    request = make_llm_request("Where is my order ORD-101?")

    result = callbacks.block_test_terms_callback(ctx, request)

    assert result is None
    assert ctx.state["conversation_history"][-1] == {
        "author": "user",
        "text": "Where is my order ORD-101?",
    }


def test_block_test_terms_callback_blocks_blocked_term():
    ctx = FakeCallbackContext()
    request = make_llm_request("Give me the COMPETITOR_DISCOUNT please")

    result = callbacks.block_test_terms_callback(ctx, request)

    assert result is not None
    assert "cannot process messages" in result.content.parts[0].text


def test_block_test_terms_callback_blocks_card_number_pattern():
    ctx = FakeCallbackContext()
    request = make_llm_request("My card is 1234567890123456")

    result = callbacks.block_test_terms_callback(ctx, request)

    assert result is not None


def test_block_test_terms_callback_handles_message_with_no_user_text():
    ctx = FakeCallbackContext()
    # A content list with no text parts: _extract_last_user_text should fall
    # through its loop and return "", and _append_history should then skip
    # recording an empty entry.
    empty_part = SimpleNamespace(text="")
    request = SimpleNamespace(contents=[SimpleNamespace(role="user", parts=[empty_part])])

    result = callbacks.block_test_terms_callback(ctx, request)

    assert result is None
    assert "conversation_history" not in ctx.state


def test_extract_last_user_text_skips_non_user_contents():
    ctx = FakeCallbackContext()
    model_content = SimpleNamespace(role="model", parts=[SimpleNamespace(text="an earlier reply")])
    user_content = SimpleNamespace(role="user", parts=[SimpleNamespace(text="the real question")])
    request = SimpleNamespace(contents=[user_content, model_content])

    callbacks.block_test_terms_callback(ctx, request)

    # The most recent *user* content should be the one recorded, with the
    # trailing model content skipped via the `continue` branch.
    assert ctx.state["conversation_history"][-1]["text"] == "the real question"


# --- refund_limit_callback (before_tool_callback) --------------------------


def test_refund_limit_callback_ignores_other_tools():
    tool = SimpleNamespace(name="get_order_status")
    ctx = FakeToolContext()
    result = callbacks.refund_limit_callback(tool, {}, ctx)
    assert result is None


def test_refund_limit_callback_blocks_over_limit_without_approval():
    tool = SimpleNamespace(name="issue_order_refund")
    ctx = FakeToolContext({"manager_approval": False})
    result = callbacks.refund_limit_callback(tool, {"refund_amount": 150.0}, ctx)
    assert result["status"] == "BLOCKED"


def test_refund_limit_callback_allows_over_limit_with_approval():
    tool = SimpleNamespace(name="issue_order_refund")
    ctx = FakeToolContext({"manager_approval": True})
    result = callbacks.refund_limit_callback(tool, {"refund_amount": 150.0}, ctx)
    assert result is None


def test_refund_limit_callback_allows_under_limit():
    tool = SimpleNamespace(name="issue_order_refund")
    ctx = FakeToolContext({"manager_approval": False})
    result = callbacks.refund_limit_callback(tool, {"refund_amount": 50.0}, ctx)
    assert result is None


def test_refund_limit_callback_falls_back_to_order_lookup_when_amount_missing():
    # issue_order_refund's tool signature doesn't take a refund_amount
    # argument, so the LLM never includes one in `args`. The callback must
    # fall back to looking up the order's actual amount from the database.
    tool = SimpleNamespace(name="issue_order_refund")
    ctx = FakeToolContext({"manager_approval": False})

    order = db.get_order("ORD-201")  # amount = 220.00, well over the $100 limit
    assert order["amount"] > callbacks.REFUND_LIMIT

    result = callbacks.refund_limit_callback(tool, {"order_id": "ORD-201"}, ctx)

    assert result["status"] == "BLOCKED"


def test_refund_limit_callback_order_not_found_defaults_to_zero():
    tool = SimpleNamespace(name="issue_order_refund")
    ctx = FakeToolContext({"manager_approval": False})
    result = callbacks.refund_limit_callback(tool, {"order_id": "ORD-NOPE"}, ctx)
    assert result is None


def test_refund_limit_callback_no_order_id_defaults_to_zero():
    tool = SimpleNamespace(name="issue_order_refund")
    ctx = FakeToolContext({"manager_approval": False})
    result = callbacks.refund_limit_callback(tool, {}, ctx)
    assert result is None


# --- customer_id_guard_callback (before_tool_callback) ---------------------


def test_customer_id_guard_allows_calls_without_order_id():
    tool = SimpleNamespace(name="add_loyalty_points")
    ctx = FakeToolContext({"customer_id": "CUST-101"})
    result = callbacks.customer_id_guard_callback(tool, {"customer_id": "CUST-101"}, ctx)
    assert result is None


def test_customer_id_guard_allows_unknown_order():
    tool = SimpleNamespace(name="get_order_status")
    ctx = FakeToolContext({"customer_id": "CUST-101"})
    result = callbacks.customer_id_guard_callback(tool, {"order_id": "ORD-NOPE"}, ctx)
    assert result is None


def test_customer_id_guard_allows_matching_customer():
    tool = SimpleNamespace(name="get_order_status")
    ctx = FakeToolContext({"customer_id": "CUST-101"})
    result = callbacks.customer_id_guard_callback(tool, {"order_id": "ORD-101"}, ctx)
    assert result is None


def test_customer_id_guard_blocks_mismatched_customer():
    tool = SimpleNamespace(name="get_order_status")
    ctx = FakeToolContext({"customer_id": "CUST-101"})
    # ORD-201 belongs to CUST-102
    result = callbacks.customer_id_guard_callback(tool, {"order_id": "ORD-201"}, ctx)
    assert result["status"] == "FORBIDDEN"
    assert "ORD-201" in result["message"]


# --- activity_logger_callback (after_tool_callback) ------------------------


def test_activity_logger_callback_appends_order_summary():
    tool = SimpleNamespace(name="get_order_status")
    ctx = FakeToolContext()
    result = callbacks.activity_logger_callback(tool, {"order_id": "ORD-101"}, ctx, {})
    assert result is None
    assert ctx.state["activity_log"] == ["Tool get_order_status called for ORD-101"]


def test_activity_logger_callback_appends_customer_summary():
    tool = SimpleNamespace(name="add_loyalty_points")
    ctx = FakeToolContext()
    callbacks.activity_logger_callback(tool, {"customer_id": "CUST-101"}, ctx, {})
    assert ctx.state["activity_log"] == ["Tool add_loyalty_points called for CUST-101"]


# --- record_agent_response_callback (after_model_callback) -----------------


def test_record_agent_response_skips_function_call_only_response():
    ctx = FakeCallbackContext(agent_name="order_tracking_agent")
    response = make_llm_response(is_function_call=True)

    result = callbacks.record_agent_response_callback(ctx, response)

    assert result is None
    assert "conversation_history" not in ctx.state


def test_record_agent_response_records_final_text():
    ctx = FakeCallbackContext(agent_name="order_tracking_agent")
    response = make_llm_response(text="Your order is on the way.")

    callbacks.record_agent_response_callback(ctx, response)

    assert ctx.state["conversation_history"][-1] == {
        "author": "order_tracking_agent",
        "text": "Your order is on the way.",
    }


def test_conversation_history_is_trimmed_to_max_turns():
    ctx = FakeCallbackContext(agent_name="order_tracking_agent")
    for i in range(callbacks.MAX_HISTORY_TURNS + 5):
        callbacks.record_agent_response_callback(ctx, make_llm_response(text=f"reply {i}"))

    assert len(ctx.state["conversation_history"]) == callbacks.MAX_HISTORY_TURNS
    assert ctx.state["conversation_history"][-1]["text"] == f"reply {callbacks.MAX_HISTORY_TURNS + 4}"
