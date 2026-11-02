"""Tests for omnicare/db.py."""

from __future__ import annotations

from omnicare import db


def test_init_db_seeds_sample_orders():
    order = db.get_order("ORD-101")
    assert order is not None
    assert order["customer_id"] == "CUST-101"
    assert order["status"] == "PROCESSING"


def test_get_order_missing_returns_none():
    assert db.get_order("ORD-DOES-NOT-EXIST") is None


def test_update_address_updates_when_processing():
    updated = db.update_address("ORD-101", "99 New Rd")
    assert updated["address"] == "99 New Rd"
    assert db.get_order("ORD-101")["address"] == "99 New Rd"


def test_update_address_noop_when_not_processing():
    before = db.get_order("ORD-102")
    assert before["status"] == "SHIPPED"

    result = db.update_address("ORD-102", "should not apply")

    assert result["address"] == before["address"]
    assert db.get_order("ORD-102")["address"] == before["address"]


def test_update_address_missing_order_returns_none():
    assert db.update_address("ORD-NOPE", "somewhere") is None


def test_mark_refunded_updates_status_and_amount():
    updated = db.mark_refunded("ORD-101", 25.0, "damaged")
    assert updated["status"] == "REFUNDED"
    assert updated["refunded_amount"] == 25.0
    assert updated["refund_reason"] == "damaged"


def test_mark_refunded_missing_order_returns_none():
    assert db.mark_refunded("ORD-NOPE", 10.0, "reason") is None


def test_add_points_increments_existing_customer():
    starting = db.get_customer_points("CUST-101")
    new_total = db.add_points("CUST-101", 50)
    assert new_total == starting + 50
    assert db.get_customer_points("CUST-101") == starting + 50


def test_add_points_unknown_customer_returns_zero():
    # Current implementation only UPDATEs an existing row; an unknown
    # customer_id matches zero rows and the balance lookup returns 0.
    result = db.add_points("CUST-UNKNOWN", 10)
    assert result == 0


def test_get_customer_points_unknown_customer_is_zero():
    assert db.get_customer_points("CUST-UNKNOWN") == 0


def test_reset_db_reseeds_sample_data():
    db.update_address("ORD-101", "changed address")
    db.reset_db()
    assert db.get_order("ORD-101")["address"] == "12 Elm St, Springfield"
