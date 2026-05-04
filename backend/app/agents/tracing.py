"""Langfuse opt-in tracing — admin-instance level, per-call routed by analytics_consent.

This module wires the LiteLLM Langfuse callback exactly once at app startup
when all three env-loaded settings are present:

    LANGFUSE_PUBLIC_KEY
    LANGFUSE_SECRET_KEY
    LANGFUSE_HOST

If any are missing, this is a no-op with an INFO log line — Langfuse is fully
optional. No Langfuse network calls happen unless an LLM call is made with a
non-empty ``metadata`` dict, which ``app/agents/llm.py:_build_langfuse_metadata``
gates on per-workspace ``analytics_consent``.

Consent routing:
- ``off``       → llm.py returns ``None`` for metadata → callback no-ops.
- ``errors_only`` → metadata is built on every call. Both success_callback and
  failure_callback are registered, so Phase 1 will trace successful calls too
  for these workspaces. This deviates from the strict spec intent ("failed
  completions only") and is documented in the spec as accepted for Phase 1.
  A stricter wrapper that drops successful traces by inspecting the
  ``analytics_mode:errors_only`` tag is a Phase 2 follow-up.
- ``full``      → both callbacks fire on every call.

Per the langfuse/skills SKILL.md, env var names are unprefixed
(``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` / ``LANGFUSE_HOST``) and
LiteLLM reads them from the process env when the callback is registered.
We therefore export the values into ``os.environ`` if they were loaded only
into ``Settings`` from a ``.env`` file.

Sources consulted (langfuse/skills repo on GitHub):
- ``skills/langfuse/SKILL.md`` — env var conventions, "fetch docs before coding"
  principle, per-trace required setup.
- ``skills/langfuse/references/instrumentation.md`` — recommended fields
  (``user_id``, ``session_id``, ``tags``), import-after-load_dotenv ordering,
  ``langfuse.flush()`` on shutdown for non-persistent processes.
- LiteLLM observability docs — ``litellm.success_callback = ['langfuse']``
  and ``litellm.failure_callback = ['langfuse']`` registration pattern, and
  the ``metadata={trace_user_id, session_id, tags, ...}`` shape used at call
  sites (matches ``llm.py:_build_langfuse_metadata`` already).
"""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import uuid4

import litellm

from app.core.config import settings

logger = logging.getLogger(__name__)

# The string LiteLLM expects to wire the (legacy, non-OTEL) Langfuse callback.
# This matches the langfuse/skills examples and the LiteLLM observability docs.
_LANGFUSE_CALLBACK_NAME = "langfuse"

_ENV_PUBLIC_KEY = "LANGFUSE_PUBLIC_KEY"
_ENV_SECRET_KEY = "LANGFUSE_SECRET_KEY"
_ENV_HOST = "LANGFUSE_HOST"

# Optional suffix appended to ``agent:<id>`` in Langfuse trace names. Eval
# suites set this to ``:eval`` so their traces are easy to filter out from
# real workspace activity in the Langfuse UI.
_ENV_TRACE_NAME_SUFFIX = "ARCHFLOW_TRACE_NAME_SUFFIX"


def trace_name_suffix() -> str:
    """Return the optional trace-name suffix from the environment, or ``""``."""
    return os.environ.get(_ENV_TRACE_NAME_SUFFIX, "") or ""


def is_langfuse_configured() -> bool:
    """Return True iff all three Langfuse env-loaded settings are present.

    Reads from ``app.core.config.settings`` (which loads ``.env``). Missing or
    empty values count as not configured.
    """
    pk = settings.langfuse_public_key
    sk = settings.langfuse_secret_key
    host = settings.langfuse_host

    pk_str = pk.get_secret_value() if pk is not None else ""
    sk_str = sk.get_secret_value() if sk is not None else ""
    host_str = host or ""
    return bool(pk_str and sk_str and host_str)


def setup_litellm_callbacks() -> None:
    """Register the Langfuse callback on LiteLLM at app startup.

    Idempotent: re-running does not register the callback twice.

    No-op (with an INFO log) when ``is_langfuse_configured()`` is False — the
    rest of the agent stack continues to work without Langfuse.

    Per langfuse/skills' instrumentation.md and the LiteLLM observability
    docs, the SDK reads ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` /
    ``LANGFUSE_HOST`` directly from ``os.environ`` once a callback fires.
    We therefore export them from ``Settings`` into the process env so a
    deployment that loads these via ``.env`` (rather than container env)
    still hits the SDK's lookup path.

    Per-call gating happens in ``llm.py:_build_langfuse_metadata`` — when the
    workspace has ``analytics_consent='off'`` it returns ``None`` and the
    Langfuse callback no-ops for that call.
    """
    if not is_langfuse_configured():
        logger.info(
            "Langfuse not configured (LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / "
            "LANGFUSE_HOST missing) — agent tracing disabled."
        )
        return

    # Export Settings values into os.environ for the LiteLLM Langfuse client.
    # Use setdefault so an explicit container env wins over .env.
    pk = settings.langfuse_public_key
    sk = settings.langfuse_secret_key
    if pk is not None:
        os.environ.setdefault(_ENV_PUBLIC_KEY, pk.get_secret_value())
    if sk is not None:
        os.environ.setdefault(_ENV_SECRET_KEY, sk.get_secret_value())
    if settings.langfuse_host:
        os.environ.setdefault(_ENV_HOST, settings.langfuse_host)

    _ensure_callback(litellm, "success_callback")
    _ensure_callback(litellm, "failure_callback")

    logger.info(
        "Langfuse callbacks registered (host=%s). Per-call routing depends on "
        "workspace analytics_consent.",
        settings.langfuse_host,
    )
    # Visible at WARNING so operators can confirm in production logs that the
    # integration wired up at startup. Keys are partially redacted.
    logger.warning(
        "Langfuse tracing enabled: host=%s public_key_prefix=%s secret_key_prefix=%s",
        settings.langfuse_host,
        _redact_key(pk.get_secret_value() if pk is not None else ""),
        _redact_key(sk.get_secret_value() if sk is not None else ""),
    )


def teardown_litellm_callbacks() -> None:
    """Best-effort cleanup. Removes our callback entry from both lists.

    Used by tests to keep the global ``litellm`` module state clean. Other
    callbacks registered by application code are preserved.
    """
    for attr in ("success_callback", "failure_callback"):
        current = getattr(litellm, attr, None)
        if not isinstance(current, list):
            continue
        setattr(
            litellm,
            attr,
            [cb for cb in current if cb != _LANGFUSE_CALLBACK_NAME],
        )


def get_archflow_langfuse_env() -> dict[str, str]:
    """Return the Langfuse credentials as a plain dict, or ``{}`` if unset.

    Useful for passing to LiteLLM as per-call kwargs in setups where global
    callbacks are not desired. Day-to-day call paths read from ``os.environ``
    via the registered callback, so most callers will not need this.
    """
    if not is_langfuse_configured():
        return {}
    pk = settings.langfuse_public_key
    sk = settings.langfuse_secret_key
    return {
        "langfuse_public_key": pk.get_secret_value() if pk is not None else "",
        "langfuse_secret_key": sk.get_secret_value() if sk is not None else "",
        "langfuse_host": settings.langfuse_host or "",
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _redact_key(value: str) -> str:
    """Return the first 8 chars of *value* followed by an ellipsis.

    Empty / very short keys are reported as ``"<empty>"`` / ``"<short>"`` so
    the startup log never leaks a full secret even when misconfigured.
    """
    if not value:
        return "<empty>"
    if len(value) < 8:
        return "<short>"
    return f"{value[:8]}..."


def _ensure_callback(module: object, attr_name: str) -> None:
    """Append our callback name to ``module.<attr_name>`` if not already present.

    Treats ``None`` / missing / non-list as an empty starting list.
    """
    current = getattr(module, attr_name, None)
    if not isinstance(current, list):
        current = []
    if _LANGFUSE_CALLBACK_NAME not in current:
        current = [*current, _LANGFUSE_CALLBACK_NAME]
        setattr(module, attr_name, current)


# ---------------------------------------------------------------------------
# AgentTracer — opens an explicit Langfuse trace + node-level spans so the UI
# shows the agent invocation as a tree (supervisor → researcher → tool calls)
# instead of a flat list of generations.
# ---------------------------------------------------------------------------


_langfuse_client: Any = None


def _get_client() -> Any:
    """Lazy-init the Langfuse SDK client. Returns ``None`` when unconfigured.

    Reads credentials from ``os.environ`` after ``setup_litellm_callbacks``
    has populated them. Cached at module level so the same TCP/auth setup
    isn't redone for every invocation.
    """
    global _langfuse_client
    if _langfuse_client is not None:
        return _langfuse_client
    if not is_langfuse_configured():
        return None
    try:
        from langfuse import Langfuse  # type: ignore[import-untyped]
    except Exception as exc:  # pragma: no cover — langfuse missing
        logger.debug("langfuse SDK unavailable: %s", exc)
        return None
    pk = settings.langfuse_public_key
    sk = settings.langfuse_secret_key
    try:
        _langfuse_client = Langfuse(
            public_key=pk.get_secret_value() if pk is not None else None,
            secret_key=sk.get_secret_value() if sk is not None else None,
            host=settings.langfuse_host,
        )
    except Exception as exc:  # pragma: no cover — bad credentials etc.
        logger.warning("failed to init Langfuse SDK client: %s", exc)
        return None
    return _langfuse_client


class AgentTracer:
    """Opens a single Langfuse trace per agent invocation, plus a span per
    node visit and an event per tool call.

    No-op when Langfuse isn't configured — every method is safe to call and
    span ids fall back to ``None`` so callers don't need to special-case the
    disabled path.

    The tracer is intentionally narrow: it does NOT capture LLM I/O — that's
    left to LiteLLM's ``langfuse`` callback, which we tell to nest its
    generation under our span via ``metadata['parent_observation_id']``.
    """

    def __init__(
        self,
        *,
        trace_id: str,
        agent_id: str,
        session_id: str,
        user_id: str,
        tags: list[str] | None = None,
        chat_input: str | None = None,
    ) -> None:
        self.trace_id = trace_id
        self._client = _get_client()
        self._trace = None
        # Maps span_id → StatefulSpanClient so end_node_span can call .end()
        # on the same handle that started the span. Without this, a second
        # ``client.span(id=...)`` call ingests as a *new* observation and the
        # original span never receives an end_time → Langfuse caps latency at
        # the trace boundary (~25s by default) which made it look like the
        # node was hung when it had actually completed.
        self._spans: dict[str, Any] = {}
        if self._client is None:
            return
        suffix = trace_name_suffix()
        trace_tags = list(tags or [])
        if suffix and "archflow:eval" not in trace_tags and suffix == ":eval":
            trace_tags.append("archflow:eval")
        try:
            self._trace = self._client.trace(
                id=trace_id,
                name=f"agent:{agent_id}{suffix}",
                session_id=session_id,
                user_id=user_id,
                tags=trace_tags,
                # Plain string at the trace root so the Langfuse UI shows
                # the user's verbatim message side-by-side with the final
                # assistant text (matches the standard "input/output" pair
                # most observability dashboards expect — see e.g.
                # ``langfuse.set_current_trace_io(input=..., output=...)``).
                input=chat_input or None,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("AgentTracer: failed to open trace: %s", exc)
            self._trace = None

    @property
    def enabled(self) -> bool:
        return self._trace is not None

    def start_node_span(
        self, *, name: str, parent_id: str | None = None
    ) -> str | None:
        """Open a span for a node visit. Returns the span's observation id
        (or ``None`` when tracing is disabled / fails).
        """
        if self._client is None or self._trace is None:
            return None
        span_id = str(uuid4())
        try:
            handle = self._client.span(
                id=span_id,
                trace_id=self.trace_id,
                parent_observation_id=parent_id,
                name=name,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("AgentTracer: span(%s) failed: %s", name, exc)
            return None
        self._spans[span_id] = handle
        return span_id

    def end_node_span(
        self,
        *,
        span_id: str | None,
        output: Any | None = None,
        level: str | None = None,
    ) -> None:
        """Close a span opened by :meth:`start_node_span`. Idempotent on
        ``span_id is None`` and on already-ended spans."""
        if span_id is None:
            return
        handle = self._spans.pop(span_id, None)
        if handle is None:
            return
        kwargs: dict[str, Any] = {"output": _coerce_jsonable(output)}
        if level:
            kwargs["level"] = level
        try:
            handle.end(**kwargs)
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("AgentTracer: span end failed: %s", exc)

    def log_tool_event(
        self,
        *,
        parent_id: str | None,
        name: str,
        input_payload: Any | None,
        output_payload: Any | None,
        status: str | None = None,
    ) -> None:
        """Emit a leaf event under ``parent_id`` capturing one tool call.

        We use ``event`` rather than ``span`` because tool execution time is
        usually negligible compared to the LLM step and a flat event keeps
        the trace tree shallow.
        """
        if self._client is None or parent_id is None:
            return
        try:
            self._client.event(
                trace_id=self.trace_id,
                parent_observation_id=parent_id,
                name=f"tool:{name}",
                input=input_payload,
                output=output_payload,
                level="ERROR" if status not in (None, "ok") else None,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("AgentTracer: tool event failed: %s", exc)

    def finish(self, *, output: Any | None = None) -> None:
        """Mark the root trace finished with optional output."""
        if self._trace is None:
            return
        try:
            self._trace.update(output=output)
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("AgentTracer: trace update failed: %s", exc)
        try:
            if self._client is not None:
                self._client.flush()
        except Exception:  # pragma: no cover — defensive
            pass


def _now() -> Any:
    """Return ``datetime.now(UTC)`` — wrapped in a helper so the module imports
    only what's needed lazily."""
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _coerce_jsonable(value: Any) -> Any:
    """Best-effort coerce arbitrary values to a JSON-serialisable shape.

    Pydantic models, dataclasses, UUIDs, etc. would otherwise blow up Langfuse
    ingestion (which silently drops the whole observation update).
    """
    if value is None:
        return None
    try:
        # Pydantic v2 models
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        # Dataclass instances
        from dataclasses import is_dataclass, asdict

        if is_dataclass(value):
            return asdict(value)
    except Exception:  # pragma: no cover — defensive
        pass
    if isinstance(value, dict):
        return {k: _coerce_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_coerce_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool):
        return value
    return str(value)
