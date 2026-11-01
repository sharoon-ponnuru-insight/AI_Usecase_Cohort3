"""Callbacks for OmniCare.

Wires up the three required callbacks:
- before_model_callback: blocks messages containing test/blocked terms.
- before_tool_callback: enforces a $100 refund limit unless manager-approved.
- after_tool_callback: appends a one-line activity log entry after each tool call.
"""

from __future__ import annotations

import re
from typing import Any

from google.genai import types

from google.adk.agents.context import Context
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool

from omnicare import db

_BLOCKED_TERMS = ("COMPETITOR_DISCOUNT",)
_CARD_PATTERN = re.compile(r"\b\d{16}\b")

REFUND_LIMIT = 100.0

# Graph-workflow nodes each run in an isolated session branch, so agents don't
# automatically see prior turns. We track a short rolling transcript in
# session.state and inject it into each agent's instruction (see agents.py).
MAX_HISTORY_TURNS = 4


def _append_history(tool_context, author: str, text: str) -> None:
    if not text:
        return
    existing = tool_context.state.get("conversation_history", [])
    updated = [*existing, {"author": author, "text": text}]
    tool_context.state["conversation_history"] = updated[-MAX_HISTORY_TURNS:]


def _extract_last_user_text(llm_request: LlmRequest) -> str:
    contents = getattr(llm_request, "contents", None) or []
    for content in reversed(contents):
        if getattr(content, "role", None) != "user":
            continue
        parts = getattr(content, "parts", None) or []
        text = " ".join(p.text for p in parts if getattr(p, "text", None))
        if text:
            return text
    return ""


def block_test_terms_callback(callback_context: Context, llm_request: LlmRequest) -> LlmResponse | None:
    """before_model_callback: blocks blocked test words / dummy card numbers before calling the LLM.

    Also records the user's message in conversation_history, since this callback
    always runs on the first (router) node of each turn.
    """
    text = _extract_last_user_text(llm_request)
    _append_history(callback_context, "user", text)

    blocked = any(term in text for term in _BLOCKED_TERMS) or bool(_CARD_PATTERN.search(text))
    if not blocked:
        return None

    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    text=(
                        "For security and policy reasons, I cannot process messages "
                        "containing that term."
                    )
                )
            ],
        )
    )


def refund_limit_callback(
    tool: BaseTool, args: dict[str, Any], tool_context: Context
) -> dict | None:
    """before_tool_callback: blocks issue_order_refund calls over $100 without manager approval."""
    if tool.name != "issue_order_refund":
        return None

    refund_amount = args.get("refund_amount", 0) or 0
    if refund_amount > REFUND_LIMIT and not tool_context.state.get("manager_approval", False):
        return {
            "status": "BLOCKED",
            "message": (
                "Refunds over $100 require Manager Approval. Please enable the "
                "Manager Approval checkbox in the UI."
            ),
        }
    return None


def customer_id_guard_callback(
    tool: BaseTool, args: dict[str, Any], tool_context: Context
) -> dict | None:
    """before_tool_callback: blocks order tool calls when the order belongs to a different customer."""
    order_id = args.get("order_id")
    if not order_id:
        return None

    order = db.get_order(order_id)
    if order is None:
        return None

    session_customer_id = tool_context.state.get("customer_id")
    if session_customer_id and order["customer_id"] != session_customer_id:
        return {
            "status": "FORBIDDEN",
            "message": f"Order {order_id} was placed by another customer.",
        }
    return None


def activity_logger_callback(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: Context,
    tool_response: dict,
) -> dict | None:
    """after_tool_callback: appends a one-line summary to tool_context.state['activity_log']."""
    order_or_customer = args.get("order_id") or args.get("customer_id") or ""
    summary = f"Tool {tool.name} called for {order_or_customer}".strip()

    existing = tool_context.state.get("activity_log", [])
    tool_context.state["activity_log"] = [*existing, summary]
    return None


def record_agent_response_callback(
    callback_context: Context, llm_response: LlmResponse
) -> LlmResponse | None:
    """after_model_callback: records an agent's final text reply in conversation_history.

    Skips intermediate responses that only contain a function call (tool
    request), since those aren't a user-visible reply.
    """
    content = getattr(llm_response, "content", None)
    parts = getattr(content, "parts", None) or []
    if any(getattr(p, "function_call", None) for p in parts):
        return None

    text = " ".join(p.text for p in parts if getattr(p, "text", None))
    _append_history(callback_context, callback_context.agent_name, text)
    return None
