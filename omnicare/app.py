"""Streamlit UI for OmniCare with Customer Authentication."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add parent directory explicitly so `from omnicare...` imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from google.genai import types

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from omnicare.agents import root_agent

APP_NAME = "omnicare"
USER_ID = "local_user"

# Mock credentials store (Mapping Customer ID to Password and Profile Name)
CUSTOMER_USERS = {
    "CUST-101": {"password": "password101", "name": "Alice Johnson"},
    "CUST-102": {"password": "password102", "name": "Bob Smith"},
}

st.set_page_config(page_title="OmniCare", page_icon="🛎️", layout="wide")


# --- Authentication Handler ---
def check_authentication() -> bool:
    """Renders a login form if the user is not authenticated."""
    if st.session_state.get("authenticated", False):
        return True

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 🛎️ OmniCare Customer Portal Login")
        with st.form("login_form"):
            selected_user = st.selectbox("Select Customer ID", list(CUSTOMER_USERS.keys()))
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In")

            if submitted:
                expected_pw = CUSTOMER_USERS[selected_user]["password"]
                if password == expected_pw:
                    st.session_state.authenticated = True
                    st.session_state.customer_id = selected_user
                    st.session_state.customer_name = CUSTOMER_USERS[selected_user]["name"]
                    st.session_state.messages = []
                    st.success("Authentication successful!")
                    st.rerun()
                else:
                    st.error("Invalid customer ID or password.")
        
        st.caption("Demo credentials: `CUST-101` / `password101` or `CUST-102` / `password102`")

    return False


# Stop execution here if user is not authenticated
if not check_authentication():
    st.stop()


# --- Main Application (runs only after successful authentication) ---
customer_id = st.session_state.customer_id


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


def _session_id_for(cust_id: str) -> str:
    return f"session-{cust_id}"


def _ensure_session(session_service: InMemorySessionService, cust_id: str):
    session_id = _session_id_for(cust_id)
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
                    "customer_id": cust_id,
                    "manager_approval": False,
                    "last_order_id": None,
                    "activity_log": [],
                },
            )
        )
    return session


def _run_turn(runner: Runner, session_id: str, user_text: str, manager_approval: bool) -> list[dict]:
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
st.sidebar.title("OmniCare Portal")
st.sidebar.markdown(f"**Logged in as:** `{customer_id}` ({st.session_state.customer_name})")

if st.sidebar.button("Sign Out"):
    st.session_state.authenticated = False
    st.session_state.customer_id = None
    st.session_state.messages = []
    st.rerun()

st.sidebar.divider()
manager_approval = st.sidebar.checkbox("Manager Approval Override", value=False)

runner, session_service = _init_runner()
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

    st.rerun()