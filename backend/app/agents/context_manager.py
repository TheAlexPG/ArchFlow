"""ContextManager and CompactionLadder — keep LLM messages within the context window.

Escalating ladder applied in order as token usage crosses ``threshold``:

  1. ``trim_large_tool_results``      — replace oversized tool replies with placeholders.
  2. ``drop_oldest_tool_messages``    — drop tool replies older than the last 4 turn-pairs.
  3. ``summarize_oldest_half``        — summarize the older 50% via a cheap LLM call.
  4. ``hard_truncate_keep_recent``    — keep only system + the last N=10 messages.

The :class:`ContextManager` is **stateless** about session storage: callers pass in
the current ``compaction_stage`` value (loaded from the
``agent_chat_session.compaction_stage`` row) and persist the new stage themselves
when :class:`CompactionResult` reports ``stage_applied > 0``.

Strategies never mutate ``role == "system"`` messages (they're load-bearing for
the agent's instructions).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import litellm

from app.agents.llm import LLMCallMetadata, LLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default ladder + tunables (mirrors spec §2.13)
# ---------------------------------------------------------------------------

DEFAULT_LADDER: list[str] = [
    "trim_large_tool_results",
    "drop_oldest_tool_messages",
    "summarize_oldest_half",
    "hard_truncate_keep_recent",
]

# Stage 2: keep tool replies belonging to the most recent ``KEEP_RECENT_TURN_PAIRS``
# (user, assistant) turn pairs; older tool replies are reduced to a sentinel.
KEEP_RECENT_TURN_PAIRS = 4

# Stage 3: how many messages at the tail must remain verbatim (in addition to
# system messages, which are *always* preserved).
SUMMARIZE_KEEP_TAIL = 4
# Length budget for the summary itself.
SUMMARY_MAX_TOKENS = 500

# Stage 4: keep only system messages plus this many messages from the tail.
HARD_TRUNCATE_KEEP_LAST = 10

# Sentinel content used by Stage 2 when a tool reply is dropped.
DROPPED_TOOL_RESULT_PLACEHOLDER = "<dropped during compaction>"


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class CompactionStrategy(Protocol):
    """A pure-ish function: messages + context → compacted messages.

    Receives :class:`LLMClient` for LLM-backed strategies; deterministic ones
    accept it and ignore it for a uniform call signature.
    """

    name: str

    async def apply(
        self,
        messages: list[dict],
        *,
        llm: LLMClient,
        call_metadata: LLMCallMetadata,
        tool_result_trim_threshold_tokens: int,
        model_override: str | None = None,
    ) -> list[dict]: ...


@dataclass
class CompactionResult:
    """Outcome of one :meth:`ContextManager.maybe_compact` call.

    ``stage_applied`` is **1-based** (matches the persistent
    ``agent_chat_session.compaction_stage``); ``0`` means no compaction ran.
    """

    compacted_messages: list[dict]
    stage_applied: int  # 0 = no-op, 1..N = ladder index
    strategy_name: str | None
    tokens_before: int
    tokens_after: int


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _is_truncation_placeholder(content: object) -> bool:
    """Return True if the message content is already a Stage-1 placeholder."""
    return isinstance(content, str) and content.startswith("<truncated:")


def _system_messages(messages: list[dict]) -> list[dict]:
    return [m for m in messages if m.get("role") == "system"]


def _non_system_messages(messages: list[dict]) -> list[dict]:
    return [m for m in messages if m.get("role") != "system"]


class TrimLargeToolResults:
    """Stage 1: replace tool messages whose content exceeds
    ``tool_result_trim_threshold_tokens`` with a placeholder
    ``"<truncated: tool_name(args), N tokens>"``.

    Operates only on ``role == "tool"`` messages. Single-message token count
    via :func:`litellm.token_counter`. Preserves order; everything else
    untouched. Idempotent — already-truncated placeholders are skipped.
    """

    name = "trim_large_tool_results"

    async def apply(
        self,
        messages: list[dict],
        *,
        llm: LLMClient,
        call_metadata: LLMCallMetadata,
        tool_result_trim_threshold_tokens: int,
        model_override: str | None = None,
    ) -> list[dict]:
        out: list[dict] = []
        for msg in messages:
            if msg.get("role") != "tool":
                out.append(msg)
                continue
            content = msg.get("content")
            if _is_truncation_placeholder(content):
                # Already trimmed — leave alone (idempotent).
                out.append(msg)
                continue
            text = content if isinstance(content, str) else str(content or "")
            try:
                tokens = litellm.token_counter(model=llm.model, text=text)
            except Exception:  # pragma: no cover — fallback
                tokens = max(1, len(text) // 4)
            if tokens <= tool_result_trim_threshold_tokens:
                out.append(msg)
                continue

            tool_name = msg.get("name") or "unknown_tool"
            placeholder = f"<truncated: {tool_name}(...), {tokens} tokens>"
            new_msg = dict(msg)
            new_msg["content"] = placeholder
            out.append(new_msg)
        return out


class DropOldestToolMessages:
    """Stage 2: keep tool replies belonging to the last
    ``KEEP_RECENT_TURN_PAIRS`` ``(user, assistant)`` pairs, replace older
    ``role == "tool"`` messages with a brief placeholder.

    A "turn pair" is a consecutive ``user`` followed by one or more
    ``assistant`` messages (which may include ``tool_calls`` and the
    corresponding ``tool`` replies). System messages are preserved untouched
    and don't count toward turn-pair detection.

    The matching ``assistant`` ``tool_calls`` are preserved (OpenAI accepts
    assistant tool_calls without paired tool replies — a function-call
    history without verbatim outputs).
    """

    name = "drop_oldest_tool_messages"

    async def apply(
        self,
        messages: list[dict],
        *,
        llm: LLMClient,
        call_metadata: LLMCallMetadata,
        tool_result_trim_threshold_tokens: int,
        model_override: str | None = None,
    ) -> list[dict]:
        # Walk non-system messages and assign a turn-pair index to each.
        # A turn-pair starts at every ``user`` message; messages before the
        # first user message belong to pair 0 (= "preamble", treated as old).
        turn_index: list[int] = []
        current = -1
        for msg in messages:
            role = msg.get("role")
            if role == "system":
                turn_index.append(-1)  # marker; never used for filtering
                continue
            if role == "user":
                current += 1
            turn_index.append(current)

        if current < 0:
            # No user messages at all — nothing to do.
            return list(messages)

        # The newest pair is ``current``; keep tool replies in pairs
        # ``[current - KEEP_RECENT_TURN_PAIRS + 1 .. current]``.
        cutoff = current - KEEP_RECENT_TURN_PAIRS + 1

        out: list[dict] = []
        for msg, t_idx in zip(messages, turn_index, strict=True):
            if msg.get("role") != "tool":
                out.append(msg)
                continue
            if t_idx >= cutoff:
                out.append(msg)
                continue
            # Old tool reply — replace content with a brief sentinel.
            new_msg = dict(msg)
            new_msg["content"] = DROPPED_TOOL_RESULT_PLACEHOLDER
            out.append(new_msg)
        return out


class SummarizeOldestHalf:
    """Stage 3: split into ``oldest 50%`` (excluding system + last
    ``SUMMARIZE_KEEP_TAIL`` messages) + ``recent``. Summarize the older half
    via a cheap LLM call and replace it with one ``role == "system"`` message
    starting with ``"## Earlier in this session\\n"``.

    The summarization model is selected via ``model_override`` (passed by
    :class:`ContextManager`) — typically the workspace's
    ``health_check_model``. We never hardcode a model name here.
    """

    name = "summarize_oldest_half"

    SUMMARY_PROMPT = (
        "You are an assistant compressing a long agent transcript. Produce a "
        "concise (<=500 tokens) summary of the conversation so far. You MUST:\n"
        "  - retain object/diagram IDs that were created or referenced\n"
        "  - retain decisions made and their rationale\n"
        "  - retain unresolved questions or pending tasks\n"
        "  - drop verbatim conversation, pleasantries, and tool-result payloads\n"
        "Output plain markdown — no headings, no preamble. Begin directly with "
        "the summary content."
    )

    async def apply(
        self,
        messages: list[dict],
        *,
        llm: LLMClient,
        call_metadata: LLMCallMetadata,
        tool_result_trim_threshold_tokens: int,
        model_override: str | None = None,
    ) -> list[dict]:
        systems = _system_messages(messages)
        non_system = _non_system_messages(messages)

        if len(non_system) <= SUMMARIZE_KEEP_TAIL:
            # Nothing to summarize — fewer messages than the keep-tail budget.
            return list(messages)

        # Reserve the tail. The remaining messages form the "summarizable"
        # block; we summarize the older 50% of *that* block.
        body = non_system[:-SUMMARIZE_KEEP_TAIL]
        tail = non_system[-SUMMARIZE_KEEP_TAIL:]

        if not body:
            return list(messages)

        half = max(1, len(body) // 2)
        to_summarize = body[:half]
        keep_body = body[half:]

        # Build the summarizer prompt as a tiny chat: system + transcript dump.
        transcript_lines: list[str] = []
        for m in to_summarize:
            role = m.get("role", "?")
            content = m.get("content")
            if isinstance(content, list):
                # OpenAI parts array — flatten textual parts only.
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            transcript_lines.append(f"[{role}] {content or ''}")
        transcript = "\n".join(transcript_lines)

        summarizer_messages: list[dict] = [
            {"role": "system", "content": self.SUMMARY_PROMPT},
            {"role": "user", "content": transcript},
        ]

        try:
            result = await llm.acompletion(
                messages=summarizer_messages,
                metadata=call_metadata,
                model_override=model_override,
                max_tokens=SUMMARY_MAX_TOKENS,
                temperature=0.0,
            )
            summary_text = (result.text or "").strip()
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(
                "summarize_oldest_half: LLM summarization failed (%s); "
                "falling back to dropping the oldest half.",
                e,
            )
            summary_text = ""

        if not summary_text:
            # Degraded mode: synthesize a minimal placeholder so we still make
            # forward progress on context size.
            summary_text = (
                f"(summary unavailable — {len(to_summarize)} earlier messages dropped)"
            )

        summary_msg = {
            "role": "system",
            "content": f"## Earlier in this session\n{summary_text}",
        }

        # Reassemble: original system messages → summary → kept body → tail.
        return [*systems, summary_msg, *keep_body, *tail]


class HardTruncateKeepRecent:
    """Stage 4 (last resort): keep all system messages + the last
    ``HARD_TRUNCATE_KEEP_LAST`` non-system messages. Drop everything else.

    The runtime is responsible for surfacing a UI banner — this strategy only
    rewrites the message list.
    """

    name = "hard_truncate_keep_recent"

    async def apply(
        self,
        messages: list[dict],
        *,
        llm: LLMClient,
        call_metadata: LLMCallMetadata,
        tool_result_trim_threshold_tokens: int,
        model_override: str | None = None,
    ) -> list[dict]:
        systems = _system_messages(messages)
        non_system = _non_system_messages(messages)
        tail = non_system[-HARD_TRUNCATE_KEEP_LAST:]
        return [*systems, *tail]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


STRATEGY_REGISTRY: dict[str, type[CompactionStrategy]] = {
    "trim_large_tool_results": TrimLargeToolResults,
    "drop_oldest_tool_messages": DropOldestToolMessages,
    "summarize_oldest_half": SummarizeOldestHalf,
    "hard_truncate_keep_recent": HardTruncateKeepRecent,
}


# ---------------------------------------------------------------------------
# ContextManager
# ---------------------------------------------------------------------------


class ContextManager:
    """Wraps a session's messages with an escalating compaction ladder.

    Stateless about the session itself — caller passes the *current*
    ``compaction_stage`` (loaded from
    ``agent_chat_session.compaction_stage``). When :meth:`maybe_compact`
    returns a :class:`CompactionResult` with ``stage_applied > 0``, the
    caller is responsible for persisting the new stage back to the session
    row.
    """

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        ladder_strategy_names: list[str] | None = None,
        tool_result_trim_threshold_tokens: int = 2000,
        summarizer_model_override: str | None = None,
    ) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError(
                f"threshold must be in (0.0, 1.0]; got {threshold!r}"
            )

        self.threshold = threshold
        self.tool_result_trim_threshold_tokens = tool_result_trim_threshold_tokens
        self.summarizer_model_override = summarizer_model_override

        names = ladder_strategy_names if ladder_strategy_names is not None else DEFAULT_LADDER
        if not names:
            raise ValueError("ladder_strategy_names must be a non-empty list")

        ladder: list[CompactionStrategy] = []
        for name in names:
            strategy_cls = STRATEGY_REGISTRY.get(name)
            if strategy_cls is None:
                valid = ", ".join(sorted(STRATEGY_REGISTRY))
                raise ValueError(
                    f"Unknown compaction strategy {name!r}. Valid keys: {valid}"
                )
            ladder.append(strategy_cls())
        self.ladder: list[CompactionStrategy] = ladder

    @property
    def ladder_names(self) -> list[str]:
        return [s.name for s in self.ladder]

    async def maybe_compact(
        self,
        messages: list[dict],
        *,
        llm: LLMClient,
        current_stage: int,
        call_metadata: LLMCallMetadata,
        tools: list[dict] | None = None,
    ) -> CompactionResult:
        """Decide whether to compact and apply the next strategy if so.

        Returns a no-op :class:`CompactionResult` (``stage_applied=0``) when
        current usage is below ``threshold``. Otherwise applies the strategy
        at index ``current_stage + 1`` (1-based, clamped to the last stage of
        the ladder) and returns the result.
        """
        tokens_before = llm.count_tokens(messages, tools=tools)
        window = llm.context_window()
        ratio = tokens_before / window if window > 0 else 1.0

        if ratio < self.threshold:
            return CompactionResult(
                compacted_messages=messages,
                stage_applied=0,
                strategy_name=None,
                tokens_before=tokens_before,
                tokens_after=tokens_before,
            )

        # Clamp to the last stage when current_stage already exceeds the ladder.
        next_stage_one_based = min(current_stage + 1, len(self.ladder))
        # Defensive: if the caller passed a stage <= 0 (unstarted), we still
        # apply stage 1.
        next_stage_one_based = max(1, next_stage_one_based)

        strategy = self.ladder[next_stage_one_based - 1]

        new_messages = await strategy.apply(
            messages,
            llm=llm,
            call_metadata=call_metadata,
            tool_result_trim_threshold_tokens=self.tool_result_trim_threshold_tokens,
            model_override=self.summarizer_model_override,
        )
        tokens_after = llm.count_tokens(new_messages, tools=tools)

        logger.info(
            "context_manager: applied stage %d (%s); tokens %d -> %d (window=%d)",
            next_stage_one_based,
            strategy.name,
            tokens_before,
            tokens_after,
            window,
        )

        return CompactionResult(
            compacted_messages=new_messages,
            stage_applied=next_stage_one_based,
            strategy_name=strategy.name,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )
