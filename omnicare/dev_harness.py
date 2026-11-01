"""Dev harness for OmniCare.

Exercises the tool functions directly against the local SQLite store,
with no LLM/network calls involved. Useful for fast iteration while
building out db.py / tools.py / callbacks.py in later phases.

Run with: python dev_harness.py
"""

from __future__ import annotations


class FakeToolContext:
    """Minimal stand-in for google.adk.tools.ToolContext.

    Only implements the `.state` dict access that our tool functions need,
    so tools can be smoke-tested without spinning up a Runner/Session.
    """

    def __init__(self, initial_state: dict | None = None):
        self.state = dict(initial_state or {})


def main() -> None:
    try:
        from omnicare import tools  # type: ignore
    except ImportError:
        print(
            "tools.py not implemented yet (Phase 4). "
            "This harness is a placeholder until db.py / tools.py exist."
        )
        return

    ctx = FakeToolContext(
        {
            "customer_id": "CUST-101",
            "manager_approval": False,
            "last_order_id": None,
            "activity_log": [],
        }
    )

    print("get_order_status:", tools.get_order_status("ORD-101", ctx))
    print("update_delivery_address:", tools.update_delivery_address("ORD-101", "123 New St", ctx))
    print("issue_order_refund:", tools.issue_order_refund("ORD-101", 25.0, "damaged", ctx))
    print("add_loyalty_points:", tools.add_loyalty_points("CUST-101", 50, ctx))
    print("final state:", ctx.state)


if __name__ == "__main__":
    main()
