"""Tests for app/agents/tracing.py.

Coverage:
- ``is_langfuse_configured`` true/false matrix.
- ``setup_litellm_callbacks`` registers ``"langfuse"`` on both lists when
  configured; no-ops + INFO log when not.
- Idempotency: calling setup twice does not duplicate the callback.
- ``teardown_litellm_callbacks`` removes our entry but leaves unrelated
  callbacks intact.
- ``get_archflow_langfuse_env`` returns dict when configured, ``{}`` when not.

No real Langfuse network calls are made — the tests only inspect the
``litellm.success_callback`` / ``failure_callback`` lists and reload the
``settings`` singleton via monkeypatch on the loaded module.
"""

from __future__ import annotations

import logging

import litellm
import pytest
from pydantic import SecretStr

from app.agents import tracing
from app.core import config as config_module

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_litellm_callbacks(monkeypatch: pytest.MonkeyPatch):
    """Snapshot + restore litellm callback state around each test.

    The litellm module holds these as module-level mutable state. Without a
    snapshot, one test's registration leaks into the next.
    """
    original_success = list(getattr(litellm, "success_callback", []) or [])
    original_failure = list(getattr(litellm, "failure_callback", []) or [])
    monkeypatch.setattr(litellm, "success_callback", original_success.copy())
    monkeypatch.setattr(litellm, "failure_callback", original_failure.copy())
    yield
    litellm.success_callback = original_success
    litellm.failure_callback = original_failure


def _set_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    public_key: str | None,
    secret_key: str | None,
    host: str | None,
) -> None:
    """Patch the singleton ``settings`` object's Langfuse fields in place."""
    s = config_module.settings
    monkeypatch.setattr(
        s,
        "langfuse_public_key",
        SecretStr(public_key) if public_key else None,
    )
    monkeypatch.setattr(
        s,
        "langfuse_secret_key",
        SecretStr(secret_key) if secret_key else None,
    )
    monkeypatch.setattr(s, "langfuse_host", host)


# ---------------------------------------------------------------------------
# is_langfuse_configured
# ---------------------------------------------------------------------------


def test_is_langfuse_configured_true_with_all_three(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_settings(
        monkeypatch,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://cloud.langfuse.com",
    )
    assert tracing.is_langfuse_configured() is True


def test_is_langfuse_configured_false_when_public_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_settings(
        monkeypatch,
        public_key=None,
        secret_key="sk-lf-test",
        host="https://cloud.langfuse.com",
    )
    assert tracing.is_langfuse_configured() is False


def test_is_langfuse_configured_false_when_secret_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_settings(
        monkeypatch,
        public_key="pk-lf-test",
        secret_key=None,
        host="https://cloud.langfuse.com",
    )
    assert tracing.is_langfuse_configured() is False


def test_is_langfuse_configured_false_when_host_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_settings(
        monkeypatch,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host=None,
    )
    assert tracing.is_langfuse_configured() is False


def test_is_langfuse_configured_false_when_all_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_settings(monkeypatch, public_key=None, secret_key=None, host=None)
    assert tracing.is_langfuse_configured() is False


# ---------------------------------------------------------------------------
# Env-var alias: LANGFUSE_HOST is canonical, LANGFUSE_BASE_URL is accepted
# as a fallback so a misnamed env var doesn't silently disable tracing.
# ---------------------------------------------------------------------------


def test_settings_picks_up_langfuse_base_url_alias(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://lf.example.test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-x")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-x")
    fresh = config_module.Settings()
    assert fresh.langfuse_host == "https://lf.example.test"


def test_settings_prefers_langfuse_host_over_base_url(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("LANGFUSE_HOST", "https://canonical.example.test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://alias.example.test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-x")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-x")
    fresh = config_module.Settings()
    assert fresh.langfuse_host == "https://canonical.example.test"


# ---------------------------------------------------------------------------
# setup_litellm_callbacks
# ---------------------------------------------------------------------------


def test_setup_registers_langfuse_on_both_lists(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_settings(
        monkeypatch,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://cloud.langfuse.com",
    )
    # Start with empty callback lists so we can assert exactly what we add.
    monkeypatch.setattr(litellm, "success_callback", [])
    monkeypatch.setattr(litellm, "failure_callback", [])

    tracing.setup_litellm_callbacks()

    assert "langfuse" in litellm.success_callback
    assert "langfuse" in litellm.failure_callback


def test_setup_exports_env_vars(monkeypatch: pytest.MonkeyPatch):
    _set_settings(
        monkeypatch,
        public_key="pk-lf-test-export",
        secret_key="sk-lf-test-export",
        host="https://cloud.langfuse.com",
    )
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)

    tracing.setup_litellm_callbacks()

    import os

    assert os.environ.get("LANGFUSE_PUBLIC_KEY") == "pk-lf-test-export"
    assert os.environ.get("LANGFUSE_SECRET_KEY") == "sk-lf-test-export"
    assert os.environ.get("LANGFUSE_HOST") == "https://cloud.langfuse.com"


def test_setup_is_idempotent(monkeypatch: pytest.MonkeyPatch):
    _set_settings(
        monkeypatch,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://cloud.langfuse.com",
    )
    monkeypatch.setattr(litellm, "success_callback", [])
    monkeypatch.setattr(litellm, "failure_callback", [])

    tracing.setup_litellm_callbacks()
    tracing.setup_litellm_callbacks()

    assert litellm.success_callback.count("langfuse") == 1
    assert litellm.failure_callback.count("langfuse") == 1


def test_setup_logs_warning_with_redacted_keys(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    """Startup must emit a WARNING line so operators can confirm wiring."""
    _set_settings(
        monkeypatch,
        public_key="pk-lf-test-deadbeef-extra",
        secret_key="sk-lf-test-cafebabe-extra",
        host="https://cloud.langfuse.com",
    )
    monkeypatch.setattr(litellm, "success_callback", [])
    monkeypatch.setattr(litellm, "failure_callback", [])

    with caplog.at_level(logging.WARNING, logger="app.agents.tracing"):
        tracing.setup_litellm_callbacks()

    msgs = [rec.getMessage() for rec in caplog.records]
    assert any("Langfuse tracing enabled" in m for m in msgs)
    # Full secrets must NOT appear in the log line.
    full = "\n".join(msgs)
    assert "pk-lf-test-deadbeef-extra" not in full
    assert "sk-lf-test-cafebabe-extra" not in full
    # Prefix (first 8 chars) should appear.
    assert "pk-lf-te" in full
    assert "sk-lf-te" in full


def test_setup_without_env_is_noop_with_info_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    _set_settings(monkeypatch, public_key=None, secret_key=None, host=None)
    monkeypatch.setattr(litellm, "success_callback", [])
    monkeypatch.setattr(litellm, "failure_callback", [])

    with caplog.at_level(logging.INFO, logger="app.agents.tracing"):
        tracing.setup_litellm_callbacks()

    assert "langfuse" not in litellm.success_callback
    assert "langfuse" not in litellm.failure_callback
    assert any("not configured" in rec.message.lower() for rec in caplog.records)


def test_setup_preserves_existing_unrelated_callbacks(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_settings(
        monkeypatch,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://cloud.langfuse.com",
    )
    monkeypatch.setattr(litellm, "success_callback", ["custom_logger"])
    monkeypatch.setattr(litellm, "failure_callback", ["pagerduty"])

    tracing.setup_litellm_callbacks()

    assert "custom_logger" in litellm.success_callback
    assert "langfuse" in litellm.success_callback
    assert "pagerduty" in litellm.failure_callback
    assert "langfuse" in litellm.failure_callback


# ---------------------------------------------------------------------------
# teardown_litellm_callbacks
# ---------------------------------------------------------------------------


def test_teardown_removes_langfuse_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        litellm, "success_callback", ["langfuse", "custom_logger"]
    )
    monkeypatch.setattr(
        litellm, "failure_callback", ["pagerduty", "langfuse"]
    )

    tracing.teardown_litellm_callbacks()

    assert litellm.success_callback == ["custom_logger"]
    assert litellm.failure_callback == ["pagerduty"]


def test_teardown_no_langfuse_present_is_noop(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(litellm, "success_callback", ["other"])
    monkeypatch.setattr(litellm, "failure_callback", [])

    tracing.teardown_litellm_callbacks()

    assert litellm.success_callback == ["other"]
    assert litellm.failure_callback == []


def test_teardown_handles_non_list_attrs(monkeypatch: pytest.MonkeyPatch):
    """If something else clobbered the attr to None, teardown must not crash."""
    monkeypatch.setattr(litellm, "success_callback", None)
    monkeypatch.setattr(litellm, "failure_callback", None)

    # Should not raise.
    tracing.teardown_litellm_callbacks()


# ---------------------------------------------------------------------------
# get_archflow_langfuse_env
# ---------------------------------------------------------------------------


def test_get_archflow_langfuse_env_when_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_settings(
        monkeypatch,
        public_key="pk-lf-abc",
        secret_key="sk-lf-xyz",
        host="https://eu.langfuse.example",
    )
    out = tracing.get_archflow_langfuse_env()
    assert out == {
        "langfuse_public_key": "pk-lf-abc",
        "langfuse_secret_key": "sk-lf-xyz",
        "langfuse_host": "https://eu.langfuse.example",
    }


def test_get_archflow_langfuse_env_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_settings(monkeypatch, public_key=None, secret_key=None, host=None)
    assert tracing.get_archflow_langfuse_env() == {}


# ---------------------------------------------------------------------------
# Sanity: setup → teardown → setup re-registers
# ---------------------------------------------------------------------------


def test_setup_teardown_setup_round_trip(monkeypatch: pytest.MonkeyPatch):
    _set_settings(
        monkeypatch,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="https://cloud.langfuse.com",
    )
    monkeypatch.setattr(litellm, "success_callback", [])
    monkeypatch.setattr(litellm, "failure_callback", [])

    tracing.setup_litellm_callbacks()
    assert "langfuse" in litellm.success_callback
    tracing.teardown_litellm_callbacks()
    assert "langfuse" not in litellm.success_callback
    tracing.setup_litellm_callbacks()
    assert "langfuse" in litellm.success_callback


# ---------------------------------------------------------------------------
# AgentTracer — chat-session-id grouping (Langfuse session_id)
# ---------------------------------------------------------------------------


class _FakeTraceHandle:
    """Records every kwarg passed to ``client.trace`` and ``trace.update``.

    Used to assert that consecutive AgentTracer instantiations for the same
    chat session both pin the trace to the SAME Langfuse ``session_id``
    (the bug this regression test guards against: follow-up messages
    showing up under a different ``session_id`` in the Langfuse UI).
    """

    def __init__(self) -> None:
        self.update_calls: list[dict] = []

    def update(self, **kwargs):  # noqa: ANN003 — match SDK signature
        self.update_calls.append(kwargs)
        return self


class _FakeLangfuseClient:
    def __init__(self) -> None:
        self.trace_calls: list[dict] = []
        self.handles: list[_FakeTraceHandle] = []

    def trace(self, **kwargs):  # noqa: ANN003
        self.trace_calls.append(kwargs)
        handle = _FakeTraceHandle()
        self.handles.append(handle)
        return handle

    def flush(self) -> None:
        return None


def test_agent_tracer_passes_chat_session_id_to_langfuse(
    monkeypatch: pytest.MonkeyPatch,
):
    """AgentTracer must propagate the chat-session-id verbatim into the
    Langfuse trace's ``session_id`` field.

    Two consecutive constructions with the same ``session_id`` (simulating
    a follow-up message in the same chat session) MUST produce traces that
    share that exact ``session_id`` so the Langfuse UI groups them.
    """
    fake = _FakeLangfuseClient()
    monkeypatch.setattr(tracing, "_get_client", lambda: fake)

    chat_session_id = "11111111-2222-3333-4444-555555555555"

    # First chat invocation.
    tracer_a = tracing.AgentTracer(
        trace_id="trace-a",
        agent_id="general",
        session_id=chat_session_id,
        user_id="user-1",
        chat_input="hello",
    )
    assert tracer_a.enabled
    tracer_a.finish(output="ok")

    # Follow-up chat invocation in the same chat session.
    tracer_b = tracing.AgentTracer(
        trace_id="trace-b",
        agent_id="general",
        session_id=chat_session_id,
        user_id="user-1",
        chat_input="follow-up",
    )
    assert tracer_b.enabled
    tracer_b.finish(output="ok")

    # Both opening calls landed the same session_id on the Langfuse trace.
    assert len(fake.trace_calls) == 2
    assert fake.trace_calls[0]["session_id"] == chat_session_id
    assert fake.trace_calls[1]["session_id"] == chat_session_id
    # Trace ids differ across invocations (one trace per round) but the
    # Langfuse session_id is shared so the UI groups them.
    assert fake.trace_calls[0]["id"] != fake.trace_calls[1]["id"]

    # finish() re-asserts session_id on the trace update so a stray late
    # upsert (e.g. from LiteLLM's langfuse callback) cannot leave the
    # trace ungrouped.
    assert fake.handles[0].update_calls
    assert fake.handles[0].update_calls[-1]["session_id"] == chat_session_id
    assert fake.handles[1].update_calls
    assert fake.handles[1].update_calls[-1]["session_id"] == chat_session_id


def test_agent_tracer_disabled_when_client_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    """When Langfuse is not configured ``_get_client()`` returns None and the
    tracer must no-op gracefully — finish() should not raise."""
    monkeypatch.setattr(tracing, "_get_client", lambda: None)

    tracer = tracing.AgentTracer(
        trace_id="trace-x",
        agent_id="general",
        session_id="abc",
        user_id="user-1",
    )
    assert tracer.enabled is False
    tracer.finish(output="ok")  # Must not raise.
