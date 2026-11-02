"""SQLite data layer for OmniCare.

Creates/seeds a local orders table on first import, and exposes small CRUD
helper functions used by omnicare/tools.py.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from omnicare.config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    status TEXT NOT NULL,
    tracking_number TEXT,
    address TEXT NOT NULL,
    amount REAL NOT NULL,
    refunded_amount REAL NOT NULL DEFAULT 0,
    refund_reason TEXT,
    delayed_or_damaged INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    loyalty_points INTEGER NOT NULL DEFAULT 0
);
"""

_SEED_ORDERS = [
    # order_id, customer_id, status, tracking_number, address, amount, delayed_or_damaged
    ("ORD-101", "CUST-101", "PROCESSING", None, "12 Elm St, Springfield", 49.99, 0),
    ("ORD-102", "CUST-101", "SHIPPED", "TRK-55821", "12 Elm St, Springfield", 89.50, 0),
    ("ORD-103", "CUST-101", "DELAYED", "TRK-55900", "12 Elm St, Springfield", 120.00, 1),
    ("ORD-104", "CUST-101", "DELIVERED", "TRK-55111", "12 Elm St, Springfield", 15.25, 0),
    ("ORD-105", "CUST-101", "delayed", "TRK-55112", "12 Elm St, Springfield", 89.25, 0),
    ("ORD-201", "CUST-102", "PROCESSING", None, "88 Oak Ave, Shelbyville", 220.00, 0),
    ("ORD-202", "CUST-102", "DELIVERED", "TRK-61234", "88 Oak Ave, Shelbyville", 34.75, 0),
    ("ORD-203", "CUST-102", "DELAYED", "TRK-61299", "88 Oak Ave, Shelbyville", 150.00, 1),
    ("ORD-204", "CUST-102", "SHIPPED", "TRK-61355", "88 Oak Ave, Shelbyville", 60.00, 0),
]

_SEED_CUSTOMERS = [
    ("CUST-101", 0),
    ("CUST-102", 0),
]


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _seed_if_empty(conn: sqlite3.Connection) -> None:
    # Uses INSERT OR IGNORE so existing order_ids are preserved,
    # and any newly added orders in _SEED_ORDERS get inserted automatically.
    conn.executemany(
        """
        INSERT OR IGNORE INTO orders
            (order_id, customer_id, status, tracking_number, address, amount, delayed_or_damaged)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        _SEED_ORDERS,
    )
    conn.executemany(
        "INSERT OR IGNORE INTO customers (customer_id, loyalty_points) VALUES (?, ?)",
        _SEED_CUSTOMERS,
    )
    conn.commit()


def init_db() -> None:
    """Create the schema and seed sample data if the DB is new/empty."""
    conn = _get_connection()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
        _seed_if_empty(conn)
    finally:
        conn.close()


def get_order(order_id: str) -> dict[str, Any] | None:
    conn = _get_connection()
    try:
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_address(order_id: str, new_address: str) -> dict[str, Any] | None:
    """Updates the address only if the order is still PROCESSING. Returns the updated row, or None if not found."""
    conn = _get_connection()
    try:
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            return None
        if row["status"] != "PROCESSING":
            return dict(row)
        conn.execute("UPDATE orders SET address = ? WHERE order_id = ?", (new_address, order_id))
        conn.commit()
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def mark_refunded(order_id: str, amount: float, reason: str) -> dict[str, Any] | None:
    conn = _get_connection()
    try:
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE orders SET status = 'REFUNDED', refunded_amount = ?, refund_reason = ? WHERE order_id = ?",
            (amount, reason, order_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def add_points(customer_id: str, points: int) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE customers SET loyalty_points = loyalty_points + ? WHERE customer_id = ?",
            (points, customer_id),
        )
        conn.commit()
        cursor.execute("SELECT loyalty_points FROM customers WHERE customer_id = ?", (customer_id,))
        row = cursor.fetchone()
        return row[0] if row else 0


def get_customer_points(customer_id: str) -> int:
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT loyalty_points FROM customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        return row["loyalty_points"] if row else 0
    finally:
        conn.close()


def reset_db() -> None:
    """Deletes the DB file and recreates/reseeds it. Useful for tests."""
    Path(DB_PATH).unlink(missing_ok=True)
    init_db()


# Ensure schema + seed data exist as soon as this module is imported.
init_db()
