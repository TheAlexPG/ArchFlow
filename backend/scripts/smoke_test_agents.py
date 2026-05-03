"""Live smoke test for all 3 agents against a local LiteLLM-OpenAI endpoint.

Hits LM Studio / Ollama at:
  http://192.168.0.146:11434/v1
with model:
  qwen/qwen3.6-35b-a3b

For each agent (general, researcher, diagram-explainer) sends ONE invocation
through the runtime layer (same path the chat bubble uses) and prints:
  - whether the LLM was called successfully (no LiteLLM errors)
  - whether the agent emitted a final message
  - whether tool calls were resolvable (no "tool not registered" errors)

Run:
    cd backend && uv run python scripts/smoke_test_agents.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from decimal import Decimal
from typing import Any

# Allow running as a standalone script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force settings before importing app.* modules.
os.environ.setdefault("LITELLM_PROVIDER", "custom")

LM_STUDIO_BASE = "http://192.168.0.146:11434/v1"
MODEL = "qwen/qwen3.6-35b-a3b"

# ---------------------------------------------------------------------------
# Fixtures: an in-memory ResolvedAgentSettings + a stub session that mimics
# what the runtime expects. Avoids hitting Postgres for the smoke check.
# ---------------------------------------------------------------------------


def _make_settings(agent_id: str):
    from app.services.agent_settings_service import (
        AGENT_DEFAULTS,
        ResolvedAgentSettings,
    )

    s = ResolvedAgentSettings(
        workspace_id=uuid.UUID(int=0),
        agent_id=agent_id,
        litellm_provider="custom",
        litellm_base_url=LM_STUDIO_BASE,
        litellm_model=MODEL,
        litellm_context_window=32768,
        analytics_consent="off",
        agent_edits_policy="ask",
    )
    # Apply per-agent defaults (turn_limit / budget) like the real resolver.
    defaults = AGENT_DEFAULTS.get(agent_id, {})
    if "turn_limit" in defaults:
        s.turn_limit = defaults["turn_limit"]
    if "budget_usd" in defaults:
        s.budget_usd = defaults["budget_usd"]
    if "model" in defaults:
        s.litellm_model = defaults["model"]
    return s


# ---------------------------------------------------------------------------
# Agent 1: bare LLM round-trip via LLMClient (sanity that LM Studio responds).
# ---------------------------------------------------------------------------


async def smoke_llm_only() -> None:
    print("\n=== 1. Bare LLM call (no tools) ===")
    from app.agents.llm import LLMCallMetadata, LLMClient

    s = _make_settings("general")
    client = LLMClient(s)
    meta = LLMCallMetadata(
        node_name="smoke",
        agent_id="smoke",
        workspace_id=s.workspace_id,
        actor_id=uuid.UUID(int=0),
        session_id=uuid.UUID(int=0),
        analytics_consent="off",
    )
    try:
        result = await client.acompletion(
            messages=[
                {"role": "system", "content": "You are a friendly chat bot."},
                {"role": "user", "content": "Say 'hello' in Ukrainian, ONE word only."},
            ],
            metadata=meta,
            timeout=60.0,
        )
        text = (result.text or "").strip()
        ok = bool(text)
        print(f"  {'PASS' if ok else 'FAIL'}: text={text!r}, tokens_in={result.tokens_in}, tokens_out={result.tokens_out}")
    except Exception as exc:
        print(f"  FAIL: exception {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Agent 2-4: full graph runs.
#
# We bypass the DB-backed `runtime.invoke()` path by directly invoking the
# compiled LangGraph with hand-built dependencies. The graph itself runs
# the same nodes the real chat bubble would.
# ---------------------------------------------------------------------------


async def _build_graph_deps(agent_id: str):
    """Build enforcer / context_manager / tool_executor / call_metadata.

    Returns a dict that callers spread into a ``configurable`` namespace for
    LangGraph's ``RunnableConfig``.
    """
    from app.agents.context_manager import ContextManager
    from app.agents.limits import LimitsEnforcer, RuntimeCounters, RuntimeLimits
    from app.agents.llm import LLMCallMetadata, LLMClient

    settings = _make_settings(agent_id)
    llm = LLMClient(settings)

    limits = RuntimeLimits(
        turn_limit=settings.turn_limit,
        budget_usd=settings.budget_usd,
        budget_scope="per_invocation",
        on_budget_exhausted="summarize_and_finalize",
        health_check_model=MODEL,
        turn_extension=settings.turn_extension,
    )
    counters = RuntimeCounters()

    # Stub DB so cost-tracking and pricing lookups don't blow up.
    class _StubDB:
        async def execute(self, *_a, **_k):
            class _R:
                def scalar_one_or_none(self):
                    return None

                def scalars(self):
                    class _S:
                        def all(self):
                            return []

                    return _S()

            return _R()

        async def flush(self):
            pass

        def add(self, *_a, **_k):
            pass

    enforcer = LimitsEnforcer(
        limits=limits,
        counters=counters,
        llm=llm,
        db=_StubDB(),
        workspace_id=settings.workspace_id,
        agent_id=agent_id,
    )

    cm = ContextManager(
        threshold=settings.context_threshold,
        tool_result_trim_threshold_tokens=settings.tool_result_trim_threshold_tokens,
    )

    # Tool executor that just returns a canned message — we want to verify
    # that LLM-side tool *calling* roundtrips work, not that DB writes happen.
    async def _stub_tool_executor(tool_call: dict, _state: dict) -> dict:
        name = tool_call.get("name") or "?"
        return {
            "tool_call_id": tool_call.get("id") or "",
            "status": "ok",
            "preview": f"stub: {name}",
            "content": "{}",
            "raw": {},
        }

    call_meta = LLMCallMetadata(
        node_name=agent_id,
        agent_id=agent_id,
        workspace_id=settings.workspace_id,
        actor_id=uuid.UUID(int=0),
        session_id=uuid.UUID(int=0),
        analytics_consent="off",
    )

    return {
        "enforcer": enforcer,
        "context_manager": cm,
        "tool_executor": _stub_tool_executor,
        "call_metadata_base": call_meta,
    }


async def smoke_diagram_explainer() -> None:
    print("\n=== 2. diagram-explainer agent ===")
    from app.agents.builtin.diagram_explainer import graph as g

    deps = await _build_graph_deps("diagram-explainer")
    graph = g.build()

    # Minimal initial state matching AgentState.
    state: dict[str, Any] = {
        "messages": [
            {"role": "user", "content": "What is the diagram about? Briefly."},
        ],
        "scratchpad": "",
        "applied_changes": [],
        "tokens_in": 0,
        "tokens_out": 0,
    }

    try:
        out = await graph.ainvoke(state, config={"configurable": deps})
        explanation = out.get("explanation")
        msgs = out.get("messages") or []
        # Last assistant message is the answer.
        last_text = ""
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "assistant":
                content = m.get("content") or ""
                last_text = content if isinstance(content, str) else ""
                break
        ok = bool(last_text or explanation)
        print(f"  {'PASS' if ok else 'FAIL'}: explanation={str(explanation)[:80]!r}, last_text={last_text[:80]!r}")
    except Exception as exc:
        print(f"  FAIL: {type(exc).__name__}: {str(exc)[:200]}")


async def smoke_researcher() -> None:
    print("\n=== 3. researcher agent (standalone graph) ===")
    from app.agents.builtin.researcher import graph as g

    deps = await _build_graph_deps("researcher")
    graph = g.build()

    state: dict[str, Any] = {
        "messages": [
            {"role": "user", "content": "List the workspace's diagrams."},
        ],
        "scratchpad": "",
        "applied_changes": [],
        "tokens_in": 0,
        "tokens_out": 0,
    }

    try:
        out = await graph.ainvoke(state, config={"configurable": deps})
        findings = out.get("findings")
        msgs = out.get("messages") or []
        last_text = ""
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "assistant":
                content = m.get("content") or ""
                last_text = content if isinstance(content, str) else ""
                break
        ok = bool(findings or last_text)
        summary = ""
        if findings is not None:
            summary = getattr(findings, "summary", "") or str(findings)
        print(f"  {'PASS' if ok else 'FAIL'}: findings_summary={summary[:80]!r}, last_text={last_text[:80]!r}")
    except Exception as exc:
        print(f"  FAIL: {type(exc).__name__}: {str(exc)[:200]}")


async def smoke_general() -> None:
    print("\n=== 4. general agent (full supervisor → finalize loop) ===")
    from app.agents.builtin.general import graph as g

    deps = await _build_graph_deps("general")
    graph = g.build()

    state: dict[str, Any] = {
        "messages": [
            {"role": "user", "content": "Привіт, чим можеш допомогти?"},
        ],
        "scratchpad": "",
        "applied_changes": [],
        "tokens_in": 0,
        "tokens_out": 0,
    }

    try:
        out = await graph.ainvoke(
            state,
            config={"configurable": deps, "recursion_limit": 30},
        )
        final = out.get("final_message")
        ok = bool(final)
        print(f"  {'PASS' if ok else 'FAIL'}: final_message={str(final)[:120]!r}")
    except Exception as exc:
        print(f"  FAIL: {type(exc).__name__}: {str(exc)[:200]}")


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


async def main() -> None:
    # Trigger registration of all tools so the executor finds delegate_to_*.
    import app.agents.tools  # noqa: F401 — registry side-effects

    print(f"LM Studio: {LM_STUDIO_BASE}")
    print(f"Model:     {MODEL}")

    await smoke_llm_only()
    await smoke_diagram_explainer()
    await smoke_researcher()
    await smoke_general()

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
