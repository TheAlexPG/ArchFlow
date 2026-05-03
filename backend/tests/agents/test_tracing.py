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
