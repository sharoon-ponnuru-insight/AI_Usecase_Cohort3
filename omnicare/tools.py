"""ADK tool functions for OmniCare.

Each function follows the ADK FunctionTool convention: typed args, a
docstring describing behavior (used to auto-generate the tool schema for
the LLM), and a `ToolContext` parameter used to read/write session state.
"""

from __future__ import annotations

from google.adk.tools import ToolContext

from omnicare import db


def get_order_status(order_id: str, tool_context: ToolContext) -> dict:
    """Looks up an order's current status, tracking number, and address.

    Args:
        order_id: The order identifier, e.g. "ORD-101".
        tool_context: Injected by ADK; used to remember the last looked-up order.

    Returns:
        A dict with the order details, or a NOT_FOUND status if it doesn't exist.
    """
    order = db.get_order(order_id)
    if order is None:
        return {"status": "NOT_FOUND", "message": f"No order found with id {order_id}."}

    tool_context.state["last_order_id"] = order_id
    return {"status": "OK", "order": order}


def update_delivery_address(order_id: str, new_address: str, tool_context: ToolContext) -> dict:
    """Updates the shipping address for an order, only if it has not shipped yet.

    Args:
        order_id: The order identifier, e.g. "ORD-101".
        new_address: The new shipping address to apply.
        tool_context: Injected by ADK; used to remember the last touched order.

    Returns:
        A dict describing the outcome: OK if updated, FAILED if the order has
        already shipped or doesn't exist.
    """
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
    order_id: str, refund_amount: float, reason: str, tool_context: ToolContext
) -> dict:
    """Marks an order as refunded in the local store and records the refund.

    Args:
        order_id: The order identifier, e.g. "ORD-101".
        refund_amount: The dollar amount to refund.
        reason: A short explanation for the refund (e.g. "damaged", "delayed").
        tool_context: Injected by ADK; used to remember the last refund amount.

    Returns:
        A dict describing the outcome.
    """
    order = db.get_order(order_id)
    if order is None:
        return {"status": "NOT_FOUND", "message": f"No order found with id {order_id}."}

    updated = db.mark_refunded(order_id, refund_amount, reason)
    tool_context.state["last_order_id"] = order_id
    tool_context.state["last_refund_amount"] = refund_amount
    return {"status": "OK", "order": updated}


def add_loyalty_points(customer_id: str, points: int, tool_context: ToolContext) -> dict:
    """Adds apology/loyalty points to a customer's balance.

    Args:
        customer_id: The customer identifier, e.g. "CUST-101".
        points: The number of points to add (positive integer).
        tool_context: Injected by ADK; unused for state but kept for consistency.

    Returns:
        A dict with the customer's new points balance.
    """
    new_total = db.add_points(customer_id, points)
    return {"status": "OK", "customer_id": customer_id, "loyalty_points": new_total}
