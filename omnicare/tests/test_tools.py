"""Tests for omnicare/tools.py.

Each tool is tested in isolation using a lightweight FakeToolContext (see
conftest.py) instead of a real ADK ToolContext, since these functions only
touch tool_context.state via dict-like .get()/__setitem__.
"""

from __future__ import annotations

import math

from omnicare import db, tools
from omnicare.tests.conftest import FakeToolContext


# --- get_order_status ---------------------------------------------------


def test_get_order_status_not_found():
    ctx = FakeToolContext()
    result = tools.get_order_status("ORD-NOPE", ctx)
    assert result["status"] == "NOT_FOUND"


def test_get_order_status_ok_sets_last_order_id():
    ctx = FakeToolContext()
    result = tools.get_order_status("ORD-101", ctx)
    assert result["status"] == "OK"
    assert result["order"]["order_id"] == "ORD-101"
    assert ctx.state["last_order_id"] == "ORD-101"


# --- update_delivery_address --------------------------------------------


def test_update_delivery_address_not_found():
    ctx = FakeToolContext()
    result = tools.update_delivery_address("ORD-NOPE", "123 St", ctx)
    assert result["status"] == "NOT_FOUND"


def test_update_delivery_address_fails_when_not_processing():
    ctx = FakeToolContext()
    result = tools.update_delivery_address("ORD-102", "123 St", ctx)  # SHIPPED
    assert result["status"] == "FAILED"
    assert db.get_order("ORD-102")["address"] != "123 St"


def test_update_delivery_address_ok_when_processing():
    ctx = FakeToolContext()
    result = tools.update_delivery_address("ORD-101", "123 St", ctx)
    assert result["status"] == "OK"
    assert result["order"]["address"] == "123 St"
    assert ctx.state["last_order_id"] == "ORD-101"


# --- issue_order_refund ---------------------------------------------------


def test_issue_order_refund_requires_reason():
    ctx = FakeToolContext()
    result = tools.issue_order_refund("ORD-101", "   ", ctx)
    assert result["status"] == "FAILED"


def test_issue_order_refund_not_found():
    ctx = FakeToolContext()
    result = tools.issue_order_refund("ORD-NOPE", "damaged", ctx)
    assert result["status"] == "NOT_FOUND"


def test_issue_order_refund_blocks_damage_claim_before_delivery():
    ctx = FakeToolContext()
    result = tools.issue_order_refund("ORD-102", "it arrived damaged", ctx)  # SHIPPED
    assert result["status"] == "FAILED"
    assert "DELIVERED" in result["message"]


def test_issue_order_refund_blocks_cancellation_once_shipped():
    ctx = FakeToolContext()
    result = tools.issue_order_refund("ORD-102", "changed my mind", ctx)  # SHIPPED
    assert result["status"] == "FAILED"


def test_issue_order_refund_processing_cancels_and_refunds():
    ctx = FakeToolContext()
    order_before = db.get_order("ORD-101")
    result = tools.issue_order_refund("ORD-101", "changed my mind", ctx)

    assert result["status"] == "OK"
    assert result["new_status"] == "CANCELLED"
    assert result["refund_amount"] == order_before["amount"]
    assert ctx.state["last_order_id"] == "ORD-101"
    assert ctx.state["last_refund_amount"] == order_before["amount"]
    assert db.get_order("ORD-101")["status"] == "CANCELLED"


def test_issue_order_refund_delivered_damaged_awards_loyalty_points():
    ctx = FakeToolContext()
    order_before = db.get_order("ORD-104")  # DELIVERED, amount 15.25
    starting_points = db.get_customer_points(order_before["customer_id"])

    result = tools.issue_order_refund("ORD-104", "box arrived damaged", ctx)

    assert result["status"] == "OK"
    assert result["new_status"] == "RETURNED"
    expected_points = max(1, math.floor(order_before["amount"] * 0.50))
    assert result["points_awarded"] == expected_points
    assert db.get_customer_points(order_before["customer_id"]) == starting_points + expected_points
    assert db.get_order("ORD-104")["status"] == "RETURNED"


def test_issue_order_refund_delivered_not_damaged_awards_no_points():
    ctx = FakeToolContext()
    order_before = db.get_order("ORD-104")
    starting_points = db.get_customer_points(order_before["customer_id"])

    result = tools.issue_order_refund("ORD-104", "no longer needed", ctx)

    assert result["status"] == "OK"
    assert result["points_awarded"] == 0
    assert db.get_customer_points(order_before["customer_id"]) == starting_points


def test_issue_order_refund_already_refunded_order_fails():
    ctx = FakeToolContext()
    tools.issue_order_refund("ORD-101", "first refund", ctx)  # PROCESSING -> CANCELLED
    result = tools.issue_order_refund("ORD-101", "second attempt", ctx)
    assert result["status"] == "FAILED"
    assert "already been closed" in result["message"]


def test_issue_order_refund_already_returned_order_fails():
    ctx = FakeToolContext()
    tools.issue_order_refund("ORD-104", "first return", ctx)  # DELIVERED -> RETURNED
    result = tools.issue_order_refund("ORD-104", "second attempt", ctx)
    assert result["status"] == "FAILED"
    assert "already been closed" in result["message"]


def test_issue_order_refund_unknown_status_hits_generic_fallback():
    # Any status outside the known set (PROCESSING/DELIVERED/SHIPPED/DELAYED/
    # CANCELLED/RETURNED) should fail with the generic fallback message.
    db.mark_refunded("ORD-101", 0.0, "setup", status="ON_HOLD")
    ctx = FakeToolContext()

    result = tools.issue_order_refund("ORD-101", "trying again", ctx)

    assert result["status"] == "FAILED"
    assert "Direct refund cannot be processed" in result["message"]


# --- add_loyalty_points ---------------------------------------------------


def test_add_loyalty_points_rejects_non_delayed_compensation_type():
    ctx = FakeToolContext()
    result = tools.add_loyalty_points("CUST-101", "ORD-103", "DAMAGED", ctx)
    assert result["status"] == "FAILED"


def test_add_loyalty_points_order_not_found():
    ctx = FakeToolContext()
    result = tools.add_loyalty_points("CUST-101", "ORD-NOPE", "DELAYED", ctx)
    assert result["status"] == "NOT_FOUND"


def test_add_loyalty_points_requires_delayed_order_status():
    ctx = FakeToolContext()
    result = tools.add_loyalty_points("CUST-101", "ORD-101", "DELAYED", ctx)  # PROCESSING
    assert result["status"] == "FAILED"


def test_add_loyalty_points_awards_ten_percent_for_delayed_order():
    ctx = FakeToolContext()
    order = db.get_order("ORD-103")  # DELAYED, amount 120.00
    starting_points = db.get_customer_points(order["customer_id"])

    result = tools.add_loyalty_points(order["customer_id"], "ORD-103", "delayed", ctx)

    expected_points = math.floor(order["amount"] * 0.10)
    assert result["status"] == "OK"
    assert result["points_awarded"] == expected_points
    assert db.get_customer_points(order["customer_id"]) == starting_points + expected_points
