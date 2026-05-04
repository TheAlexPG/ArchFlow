"""LiteLLM in-process wrapper.

Owns: provider auth, token counting, context-window introspection, Langfuse
metadata pass-through, cost computation, and result normalization.

Does NOT own: budget enforcement (``limits.py``), compaction (``context_manager.py``),
tracing wiring (``tracing.py``), pricing resolution (``pricing.py``).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

import litellm
from litellm.exceptions import BadRequestError, ContextWindowExceededError
from litellm.types.utils import ModelResponse

from app.agents.errors import AgentError, ContextOverflow
from app.services.agent_settings_service import ResolvedAgentSettings

logger = logging.getLogger(__name__)

_DEFAULT_CONTEXT_WINDOW_FALLBACK = 8192
_LANGFUSE_PUBLIC_KEY_ENV = "LANGFUSE_PUBLIC_KEY"


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LLMCallMetadata:
    """Metadata propagated to litellm.acompletion for tracing."""

    workspace_id: UUID
    agent_id: str
    session_id: UUID
    actor_id: UUID  # user_id or api_key_id
    analytics_consent: str  # 'off' | 'errors_only' | 'full'
    prompt_version: str | None = None  # git SHA of prompt file (set by node)
    node_name: str | None = None
    step_index: int | None = None
    context_kind: str | None = None  # 'diagram' | 'object' | 'workspace' | 'none'
    # One trace_id per agent invocation (chat round). Multiple LLM calls in the
    # same round share this so Langfuse groups them under one trace.
    trace_id: str | None = None
    # Set by node wrappers when they open a Langfuse span. LiteLLM nests the
    # auto-traced generation under this observation so the trace shows
    # supervisor → researcher → tools as a tree, not a flat sibling list.
    parent_observation_id: str | None = None


@dataclass
class LLMResult:
    """Normalized completion result."""

    text: str | None
    tool_calls: list[dict] | None  # [{id, name, arguments}]
    finish_reason: str
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal | None  # None if pricing not resolvable
    raw: ModelResponse  # underlying response, for langfuse / debugging


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LLMClient:
    """Thin in-process wrapper around ``litellm.acompletion``.

    See module docstring for the responsibility boundary.
    """

    def __init__(self, settings: ResolvedAgentSettings) -> None:
        self._settings = settings

    # -- public properties -------------------------------------------------

    @property
    def model(self) -> str:
        return self._settings.litellm_model

    # -- non-streaming call -----------------------------------------------

    async def acompletion(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        response_format: dict | None = None,
        metadata: LLMCallMetadata,
        model_override: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: float = 600.0,
    ) -> LLMResult:
        """Make one chat completion call. Non-streaming."""
        kwargs = self._build_call_kwargs(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            metadata=metadata,
            model_override=model_override,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            stream=False,
        )
        logger.warning(
            "LLM call: model=%s api_base=%s provider=%s msgs=%d tools=%d",
            kwargs.get("model"),
            kwargs.get("api_base"),
            kwargs.get("custom_llm_provider"),
            len(kwargs.get("messages") or []),
            len(kwargs.get("tools") or []),
        )
        try:
            resp: ModelResponse = await litellm.acompletion(**kwargs)
        except ContextWindowExceededError as e:
            raise ContextOverflow(str(e)) from e
        except BadRequestError as e:
            # Some providers wrap context-length errors in plain BadRequestError.
            if _looks_like_context_length(str(e)):
                raise ContextOverflow(str(e)) from e
            logger.warning("LiteLLM BadRequest: %s", e)
            raise AgentError(f"LiteLLM bad request: {e}") from e
        except Exception as e:
            logger.warning("LiteLLM call failed: %s", e, exc_info=True)
            raise AgentError(f"LiteLLM call failed: {e}") from e

        await self._post_call_redact(resp)
        return self._normalize_response(resp, kwargs["messages"], kwargs.get("tools"))

    # -- streaming variant -------------------------------------------------

    async def astream(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        metadata: LLMCallMetadata,
        model_override: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: float = 600.0,
    ) -> AsyncIterator[dict]:
        """Async generator yielding StreamingDelta dicts.

        Event kinds:
          - {kind: 'token', text: str}
          - {kind: 'tool_call_start', id: str, name: str, args_partial: str}
          - {kind: 'tool_call_delta', id: str, args_partial: str}
          - {kind: 'finish', reason: str, tool_calls: list[dict],
                              tokens_in: int, tokens_out: int, cost_usd: Decimal|None}
        """
        kwargs = self._build_call_kwargs(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=None,
            metadata=metadata,
            model_override=model_override,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            stream=True,
        )
        try:
            stream = await litellm.acompletion(**kwargs)
        except ContextWindowExceededError as e:
            raise ContextOverflow(str(e)) from e
        except BadRequestError as e:
            if _looks_like_context_length(str(e)):
                raise ContextOverflow(str(e)) from e
            raise AgentError(f"LiteLLM bad request: {e}") from e
        except Exception as e:  # pragma: no cover
            raise AgentError(f"LiteLLM stream failed: {e}") from e

        assembled_text: list[str] = []
        # tool_call_id → {"name": str, "args": str}
        tool_calls_acc: dict[str, dict[str, str]] = {}
        finish_reason: str = "stop"
        usage_in: int | None = None
        usage_out: int | None = None
        last_chunk: Any = None

        async for chunk in stream:
            last_chunk = chunk
            if not getattr(chunk, "choices", None):
                continue
            choice = chunk.choices[0]
            delta = getattr(choice, "delta", None)
            # Text delta
            if delta is not None and getattr(delta, "content", None):
                assembled_text.append(delta.content)
                yield {"kind": "token", "text": delta.content}

            # Tool-call deltas
            if delta is not None and getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    tc_id = getattr(tc, "id", None) or ""
                    fn = getattr(tc, "function", None)
                    name = getattr(fn, "name", None) if fn else None
                    args_partial = getattr(fn, "arguments", "") if fn else ""
                    if tc_id and tc_id not in tool_calls_acc:
                        tool_calls_acc[tc_id] = {"name": name or "", "args": ""}
                        yield {
                            "kind": "tool_call_start",
                            "id": tc_id,
                            "name": name or "",
                            "args_partial": args_partial or "",
                        }
                    if args_partial:
                        # Accumulate to whichever id matches; if no id on delta,
                        # fall back to the most recently started call.
                        target_id = tc_id or (
                            next(reversed(tool_calls_acc)) if tool_calls_acc else ""
                        )
                        if target_id and target_id in tool_calls_acc:
                            tool_calls_acc[target_id]["args"] += args_partial
                            yield {
                                "kind": "tool_call_delta",
                                "id": target_id,
                                "args_partial": args_partial,
                            }

            if getattr(choice, "finish_reason", None):
                finish_reason = choice.finish_reason

            # Some providers emit usage on the final chunk.
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                usage_in = getattr(usage, "prompt_tokens", usage_in)
                usage_out = getattr(usage, "completion_tokens", usage_out)

        # Finalize: token counts + cost
        full_text = "".join(assembled_text)
        tokens_in = (
            usage_in
            if usage_in is not None
            else self.count_tokens(messages, tools=tools)
        )
        if usage_out is not None:
            tokens_out = usage_out
        else:
            try:
                tokens_out = litellm.token_counter(
                    model=kwargs["model"], text=full_text
                )
            except Exception:  # pragma: no cover
                tokens_out = 0

        cost_usd = self._safe_completion_cost(last_chunk) if last_chunk is not None else None

        finish_tool_calls = [
            {"id": tc_id, "name": v["name"], "arguments": v["args"]}
            for tc_id, v in tool_calls_acc.items()
        ]

        yield {
            "kind": "finish",
            "reason": finish_reason,
            "tool_calls": finish_tool_calls,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
        }

    # -- token & window introspection -------------------------------------

    def count_tokens(
        self, messages: list[dict], *, tools: list[dict] | None = None
    ) -> int:
        """Pre-flight token count for messages (and optional tool definitions)."""
        try:
            return litellm.token_counter(
                model=self.model, messages=messages, tools=tools
            )
        except Exception:  # pragma: no cover — extremely defensive
            # Fallback: approximate by serialized length / 4.
            payload = json.dumps({"messages": messages, "tools": tools})
            return max(1, len(payload) // 4)

    def context_window(self, *, model_override: str | None = None) -> int:
        """Return the maximum context window for the resolved model.

        Resolution order:
          1. Explicit ``litellm_context_window`` override (workspace setting),
             only when ``model_override`` is None or matches the resolved model.
          2. ``litellm.get_max_tokens(target)``.
          3. ``_DEFAULT_CONTEXT_WINDOW_FALLBACK`` (8192) with a warning.
        """
        target = model_override or self.model
        override = self._settings.litellm_context_window
        if override is not None and (model_override is None or model_override == self.model):
            return override
        try:
            value = litellm.get_max_tokens(target)
        except Exception:
            logger.warning(
                "LiteLLM does not know context window for model %r; "
                "falling back to %d tokens. Set a manual override in workspace "
                "agent settings to silence this warning.",
                target,
                _DEFAULT_CONTEXT_WINDOW_FALLBACK,
            )
            return _DEFAULT_CONTEXT_WINDOW_FALLBACK
        if not isinstance(value, int) or value <= 0:
            logger.warning(
                "LiteLLM returned invalid window %r for %r; falling back to %d",
                value,
                target,
                _DEFAULT_CONTEXT_WINDOW_FALLBACK,
            )
            return _DEFAULT_CONTEXT_WINDOW_FALLBACK
        return value

    # -- internal helpers --------------------------------------------------

    def _build_call_kwargs(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: str | dict | None,
        response_format: dict | None,
        metadata: LLMCallMetadata,
        model_override: str | None,
        max_tokens: int | None,
        temperature: float | None,
        timeout: float,
        stream: bool,
    ) -> dict[str, Any]:
        model = model_override or self.model
        api_key = self._settings.litellm_api_key()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "timeout": timeout,
        }
        if api_key is not None:
            kwargs["api_key"] = api_key
        if self._settings.litellm_base_url is not None:
            # api_base is the parameter name LiteLLM uses across all providers;
            # base_url alone is honored only by some routes.
            kwargs["api_base"] = self._settings.litellm_base_url

        provider = (self._settings.litellm_provider or "").lower()
        base_url = self._settings.litellm_base_url or ""
        # OpenRouter is OpenAI-compatible but our model names look like
        # ``anthropic/...`` / ``openai/...`` (matching OpenRouter's own
        # catalog). Without an explicit override LiteLLM routes by model
        # prefix and tries the native Anthropic / OpenAI SDK against the
        # OpenRouter URL — yielding ``AnthropicException: Unable to get
        # json response`` and an HTML 404 in the body. Treat both
        # ``provider=openrouter`` and any base_url that points at
        # ``openrouter.ai`` as OpenAI-protocol.
        is_openrouter = provider == "openrouter" or "openrouter.ai" in base_url
        if is_openrouter:
            kwargs["custom_llm_provider"] = "openai"
            if not kwargs.get("api_base"):
                kwargs["api_base"] = "https://openrouter.ai/api/v1"
        # For provider=custom (LM Studio / Ollama / vLLM / any OpenAI-compatible
        # endpoint) force OpenAI protocol regardless of model name prefix —
        # otherwise LiteLLM routes by prefix (e.g. "qwen/..." → Alibaba Qwen
        # DashScope API) and ignores the custom base URL.
        elif provider == "custom":
            kwargs["custom_llm_provider"] = "openai"
            # Many local servers don't enforce auth — pass a placeholder so the
            # OpenAI client doesn't refuse to send a request without one.
            kwargs.setdefault("api_key", "lm-studio")
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if response_format is not None:
            kwargs["response_format"] = response_format
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        if stream:
            kwargs["stream"] = True

        lf_meta = self._build_langfuse_metadata(metadata)
        # Always pass a metadata dict — empty when callbacks should no-op.
        kwargs["metadata"] = lf_meta if lf_meta is not None else {}
        return kwargs

    def _normalize_response(
        self,
        resp: ModelResponse,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> LLMResult:
        choice = resp.choices[0]
        message = getattr(choice, "message", None)
        text: str | None = getattr(message, "content", None) if message else None
        finish_reason = getattr(choice, "finish_reason", "stop") or "stop"

        tool_calls_raw = getattr(message, "tool_calls", None) if message else None
        tool_calls: list[dict] | None = None
        if tool_calls_raw:
            tool_calls = []
            for tc in tool_calls_raw:
                fn = getattr(tc, "function", None)
                tool_calls.append(
                    {
                        "id": getattr(tc, "id", None),
                        "name": getattr(fn, "name", None) if fn else None,
                        "arguments": getattr(fn, "arguments", None) if fn else None,
                    }
                )

        usage = getattr(resp, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", None) if usage else None
        tokens_out = getattr(usage, "completion_tokens", None) if usage else None
        if tokens_in is None:
            tokens_in = self.count_tokens(messages, tools=tools)
        if tokens_out is None:
            try:
                tokens_out = litellm.token_counter(
                    model=self.model, text=text or ""
                )
            except Exception:  # pragma: no cover
                tokens_out = 0

        cost_usd = self._safe_completion_cost(resp)

        return LLMResult(
            text=text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            tokens_in=int(tokens_in or 0),
            tokens_out=int(tokens_out or 0),
            cost_usd=cost_usd,
            raw=resp,
        )

    @staticmethod
    def _safe_completion_cost(resp: Any) -> Decimal | None:
        try:
            cost = litellm.completion_cost(completion_response=resp)
        except Exception:
            return None
        if cost is None or cost == 0:
            return None
        try:
            return Decimal(str(cost))
        except Exception:  # pragma: no cover
            return None

    def _build_langfuse_metadata(
        self, call_meta: LLMCallMetadata
    ) -> dict | None:
        """Build per-call metadata for the LiteLLM Langfuse callback.

        Returns ``None`` if analytics is off or the deployment Langfuse public
        key is not configured. The actual Langfuse credentials are loaded from
        env vars at app startup by ``app/agents/tracing.py`` (task 013); this
        method only constructs the trace identifying info.
        """
        if call_meta.analytics_consent == "off":
            return None
        if not os.environ.get(_LANGFUSE_PUBLIC_KEY_ENV):
            return None
        # Optional suffix (e.g. ":eval") so eval runs are filterable in the
        # Langfuse UI. Read lazily here so tests can flip it via monkeypatch.
        from app.agents.tracing import trace_name_suffix

        name_suffix = trace_name_suffix()
        # LiteLLM Langfuse integration recognises these top-level metadata keys
        # (see https://docs.litellm.ai/docs/observability/langfuse_integration):
        #   trace_id, session_id, trace_name, generation_name, tags, user_id,
        #   trace_user_id. Setting trace_id groups every LLM call in this
        #   invocation under one Langfuse trace; session_id groups multiple
        #   chat rounds under one Langfuse session.
        tags = [
            f"agent:{call_meta.agent_id}",
            f"workspace:{call_meta.workspace_id}",
            f"context:{call_meta.context_kind or 'none'}",
            f"analytics_mode:{call_meta.analytics_consent}",
            f"model:{self.model}",
            f"prompt_version:{call_meta.prompt_version or 'n/a'}",
            f"node:{call_meta.node_name or 'n/a'}",
        ]
        if name_suffix == ":eval":
            tags.append("archflow:eval")
        meta: dict[str, Any] = {
            "session_id": str(call_meta.session_id),
            "trace_name": f"agent:{call_meta.agent_id}{name_suffix}",
            "generation_name": call_meta.node_name or "llm_call",
            "user_id": str(call_meta.actor_id),
            # Kept for back-compat with earlier docs/recipes that read these.
            "trace_user_id": str(call_meta.actor_id),
            "trace_session_id": str(call_meta.session_id),
            "tags": tags,
        }
        if call_meta.trace_id is not None:
            meta["trace_id"] = call_meta.trace_id
        if call_meta.parent_observation_id is not None:
            meta["parent_observation_id"] = call_meta.parent_observation_id
        return meta

    async def _post_call_redact(self, raw: ModelResponse) -> None:
        """Hook for redaction.py — no-op in this task. Wired in task 013."""
        return None


# ---------------------------------------------------------------------------
# Helpers (module-level)
# ---------------------------------------------------------------------------


def _looks_like_context_length(message: str) -> bool:
    needles = (
        "context_length_exceeded",
        "context length",
        "maximum context length",
        "context window",
    )
    lower = message.lower()
    return any(n in lower for n in needles)
