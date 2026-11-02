"""Shared pytest fixtures for the OmniCare test suite.

Key design choice: every test gets a fresh, isolated SQLite database (via a
tmp_path file) by monkeypatching `omnicare.db.DB_PATH` before calling
`db.init_db()`. This means tests never touch the real omnicare.db seed data
and can run in any order without interfering with each other.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from omnicare import db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point omnicare.db at a throwaway SQLite file, freshly seeded per test."""
    test_db_path = tmp_path / "test_omnicare.db"
    monkeypatch.setattr(db, "DB_PATH", test_db_path)
    db.init_db()
    yield db


class FakeToolContext:
    """Minimal stand-in for google.adk.tools.ToolContext: just a mutable .state dict."""

    def __init__(self, state: dict | None = None):
        self.state = dict(state or {})


class FakeCallbackContext:
    """Minimal stand-in for the Context passed to before/after_model callbacks."""

    def __init__(self, state: dict | None = None, agent_name: str = "test_agent"):
        self.state = dict(state or {})
        self.agent_name = agent_name


class FakeReadonlyContext:
    """Minimal stand-in for ReadonlyContext, used by instruction callables."""

    def __init__(self, state: dict | None = None):
        self.state = dict(state or {})


def make_llm_request(user_text: str):
    """Builds a duck-typed object mimicking google.adk.models.llm_request.LlmRequest."""
    part = SimpleNamespace(text=user_text)
    content = SimpleNamespace(role="user", parts=[part])
    return SimpleNamespace(contents=[content])


def make_llm_response(text: str | None = None, is_function_call: bool = False):
    """Builds a duck-typed object mimicking google.adk.models.llm_response.LlmResponse."""
    if is_function_call:
        part = SimpleNamespace(text=None, function_call=SimpleNamespace(name="some_tool"))
    else:
        part = SimpleNamespace(text=text, function_call=None)
    content = SimpleNamespace(parts=[part])
    return SimpleNamespace(content=content)


@pytest.fixture
def fake_tool_context():
    return FakeToolContext


@pytest.fixture
def fake_callback_context():
    return FakeCallbackContext


@pytest.fixture
def fake_readonly_context():
    return FakeReadonlyContext
