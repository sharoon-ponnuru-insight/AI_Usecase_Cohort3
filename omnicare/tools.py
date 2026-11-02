"""ADK tool functions for OmniCare."""

from __future__ import annotations

import math
from google.adk.tools import ToolContext
from omnicare import db


def get_order_status(order_id: str, tool_context: ToolContext) -> dict:
    """Looks up an order's current status, tracking number, and address."""
    order = db.get_order(order_id)
    if order is None:
        return {"status": "NOT_FOUND", "message": f"No order found with id {order_id}."}

    tool_context.state["last_order_id"] = order_id
    return {"status": "OK", "order": order}


def update_delivery_address(order_id: str, new_address: str, tool_context: ToolContext) -> dict:
    """Updates the shipping address for an order, only if it has not shipped yet."""
    order = db.get_order(order_id)
    if order is None:
        return {"status": "NOT_FOUND", "message": f"No order found with id {order_id}."}

    if order["status"] != "PROCESSING":
        return {
            "status": "FAILED",
            "message": (
                f"Order {order_id} is already '{order['status']}' and its address "
                "can no longer be changed."
            ),
        }

    updated = db.update_address(order_id, new_address)
    tool_context.state["last_order_id"] = order_id
    return {"status": "OK", "order": updated}


def issue_order_refund(
    order_id: str, reason: str, tool_context: ToolContext
) -> dict:
    """Processes an order cancellation or return and issues a full refund.
    
    If the return is due to damage on a DELIVERED order, automatically credits
    an additional 50% of the order cost as apology loyalty points.
    """
    if not reason or not reason.strip():
        return {
            "status": "FAILED",
            "message": "A mandatory reason must be provided to process a refund, cancellation, or return.",
        }

    order = db.get_order(order_id)
    if order is None:
        return {"status": "NOT_FOUND", "message": f"No order found with id {order_id}."}

    current_status = (order.get("status") or "").upper()
    refund_amount = float(order.get("amount", 0.0))
    customer_id = order.get("customer_id")
    clean_reason = reason.strip()
    is_damaged = any(w in clean_reason.lower() for w in ("damage", "broken", "defective", "faulty"))

    # Guard: Shipped or in-transit orders cannot be "damaged" or cancelled directly
    if current_status in ("SHIPPED", "DELAYED"):
        if is_damaged:
            return {
                "status": "FAILED",
                "message": (
                    f"Order {order_id} is currently '{current_status}' and has not been delivered yet. "
                    "Damage claims, returns, and refunds can only be processed once the package is DELIVERED."
                ),
            }
        return {
            "status": "FAILED",
            "message": (
                f"Order {order_id} is currently '{current_status}'. Shipped orders "
                "cannot be directly cancelled or returned until they have been delivered."
            ),
        }

    # 1. PROCESSING -> Cancellation & Full Refund
    if current_status == "PROCESSING":
        if hasattr(db, "update_order_status"):
            db.update_order_status(order_id, "CANCELLED")
        updated = db.mark_refunded(order_id, refund_amount, clean_reason)

        tool_context.state["last_order_id"] = order_id
        tool_context.state["last_refund_amount"] = refund_amount

        return {
            "status": "OK",
            "action": "Order Cancellation & Refund",
            "order_id": order_id,
            "new_status": "CANCELLED",
            "refund_amount": refund_amount,
            "reason": clean_reason,
            "message": f"Order {order_id} was successfully cancelled and refunded for ${refund_amount:.2f}.",
            "order": updated,
        }

    # 2. DELIVERED -> Item Return & Full Refund (+ 50% Loyalty Points if Damaged)
    if current_status == "DELIVERED":
        if hasattr(db, "update_order_status"):
            db.update_order_status(order_id, "RETURNED")
        updated = db.mark_refunded(order_id, refund_amount, clean_reason)

        tool_context.state["last_order_id"] = order_id
        tool_context.state["last_refund_amount"] = refund_amount

        loyalty_msg = ""
        points_awarded = 0
        if is_damaged and customer_id:
            points_awarded = max(1, math.floor(refund_amount * 0.50))
            new_balance = db.add_points(customer_id, points_awarded)
            loyalty_msg = (
                f" Additionally, {points_awarded} apology loyalty points (50% of order value) "
                f"have been credited to account {customer_id} (new balance: {new_balance})."
            )

        return {
            "status": "OK",
            "action": "Item Return & Refund",
            "order_id": order_id,
            "new_status": "RETURNED",
            "refund_amount": refund_amount,
            "points_awarded": points_awarded,
            "reason": clean_reason,
            "message": (
                f"Item return initiated and full refund of ${refund_amount:.2f} processed for order {order_id}."
                f"{loyalty_msg}"
            ),
            "order": updated,
        }

    if current_status in ("CANCELLED", "RETURNED"):
        return {
            "status": "FAILED",
            "message": f"Order {order_id} has already been closed with status '{current_status}'.",
        }

    return {
        "status": "FAILED",
        "message": f"Direct refund cannot be processed for order {order_id} with status '{current_status}'.",
    }


def add_loyalty_points(
    customer_id: str,
    order_id: str,
    compensation_type: str,
    tool_context: ToolContext,
) -> dict:
    """Awards apology loyalty points based on order cost (10% for delays)."""
    comp_type = (compensation_type or "").strip().upper()
    if comp_type != "DELAYED":
        return {
            "status": "FAILED",
            "message": "add_loyalty_points only handles 'DELAYED'. Damaged returns receive points automatically via issue_order_refund.",
        }

    order = db.get_order(order_id)
    if order is None:
        return {"status": "NOT_FOUND", "message": f"Order {order_id} not found."}

    order_status = (order.get("status") or "").upper()
    order_cost = float(order.get("amount", 0.0))

    if order_status != "DELAYED":
        return {
            "status": "FAILED",
            "message": f"Cannot award delay points: Order {order_id} has status '{order_status}', not DELAYED.",
        }

    points_to_award = math.floor(order_cost * 0.10)
    new_total = db.add_points(customer_id, points_to_award)

    return {
        "status": "OK",
        "order_id": order_id,
        "compensation_type": "DELAYED",
        "order_cost": order_cost,
        "points_awarded": points_to_award,
        "customer_id": customer_id,
        "new_loyalty_balance": new_total,
        "message": f"Successfully credited {points_to_award} loyalty points (10% of ${order_cost:.2f}) for delayed order {order_id}.",
    }