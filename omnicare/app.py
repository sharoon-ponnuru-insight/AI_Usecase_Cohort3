"""Streamlit UI for OmniCare (used instead of `adk web`)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# `streamlit run` adds this file's directory (omnicare/) to sys.path, not its
# parent, so the `omnicare` package wouldn't otherwise be importable. Add the
# parent directory explicitly so `from omnicare...` imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from google.genai import types

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from omnicare.agents import root_agent

APP_NAME = "omnicare"
USER_ID = "local_user"
CUSTOMERS = ["CUST-101", "CUST-102"]

st.set_page_config(page_title="OmniCare", page_icon="🛎️", layout="wide")


def _init_runner() -> tuple[Runner, InMemorySessionService]:
    if "session_service" not in st.session_state:
        st.session_state.session_service = InMemorySessionService()
    if "runner" not in st.session_state:
        st.session_state.runner = Runner(
            app_name=APP_NAME,
            agent=root_agent,
            session_service=st.session_state.session_service,
        )
    return st.session_state.runner, st.session_state.session_service


def _session_id_for(customer_id: str) -> str:
    return f"session-{customer_id}"


def _ensure_session(session_service: InMemorySessionService, customer_id: str):
    session_id = _session_id_for(customer_id)
    session = asyncio.run(
        session_service.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)
    )
    if session is None:
        session = asyncio.run(
            session_service.create_session(
                app_name=APP_NAME,
                user_id=USER_ID,
                session_id=session_id,
                state={
                    "customer_id": customer_id,
                    "manager_approval": False,
                    "last_order_id": None,
                    "activity_log": [],
                },
            )
        )
    return session


def _run_turn(runner: Runner, session_id: str, user_text: str, manager_approval: bool) -> list[dict]:
    """Runs one turn and returns a list of {author, text} response chunks."""

    async def _collect() -> list[dict]:
        responses: list[dict] = []
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=user_text)]),
            state_delta={"manager_approval": manager_approval},
        ):
            if event.is_final_response() and event.content and event.content.parts:
                text = "".join(p.text for p in event.content.parts if getattr(p, "text", None))
                if text:
                    responses.append({"author": event.author, "text": text})
        return responses

    return asyncio.run(_collect())


# --- Sidebar ---
st.sidebar.title("OmniCare Controls")
customer_id = st.sidebar.selectbox("Sample customer", CUSTOMERS)
manager_approval = st.sidebar.checkbox("Manager Approval Override", value=False)

runner, session_service = _init_runner()

if st.session_state.get("active_customer_id") != customer_id:
    st.session_state.active_customer_id = customer_id
    st.session_state.messages = []

session = _ensure_session(session_service, customer_id)
session_id = _session_id_for(customer_id)

st.sidebar.markdown("### Session state")
st.sidebar.json(
    {
        "customer_id": session.state.get("customer_id"),
        "manager_approval": manager_approval,
        "last_order_id": session.state.get("last_order_id"),
    }
)
st.sidebar.markdown("### Activity log")
st.sidebar.json(session.state.get("activity_log", []))

# --- Chat window ---
st.title("🛎️ OmniCare Concierge")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant" and msg.get("agent"):
            st.caption(f"Answered by: `{msg['agent']}`")
        st.markdown(msg["text"])

if user_text := st.chat_input("Ask about an order, a return, or a refund..."):
    st.session_state.messages.append({"role": "user", "text": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            responses = _run_turn(runner, session_id, user_text, manager_approval)
        if not responses:
            st.markdown("(no response)")
        for resp in responses:
            st.caption(f"Answered by: `{resp['author']}`")
            st.markdown(resp["text"])
            st.session_state.messages.append(
                {"role": "assistant", "text": resp["text"], "agent": resp["author"]}
            )

    # Refresh the sidebar state/activity-log view after this turn.
    st.rerun()
