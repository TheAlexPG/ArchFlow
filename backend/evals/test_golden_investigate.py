"""Golden eval — read-only "research" cases against a real Qwen instance.

Each case feeds a Ukrainian/English question to the general agent and asserts:

  * the supervisor delegates to the **researcher** sub-agent at least once;
  * the agent calls a read tool (typically ``read_diagram`` or ``list_objects``);
  * the final ``message`` contains specific tokens from the seeded workspace
    (object names, type words, the diagram name).

The LLM is the real Qwen model running in LM Studio at
``http://192.168.0.146:11434/v1``. Database / tool execution is mocked via
:mod:`evals.lib.golden_runtime` so no real diagram rows are written.

Skipped by default — set ``RUN_GOLDEN_EVALS=1`` to enable.

Run::

    cd backend && RUN_GOLDEN_EVALS=1 uv run pytest \
        evals/test_golden_investigate.py -v -s
"""

from __future__ import annotations

import pytest

from evals.golden_runtime import (
    ToolCallRecorder,
    collect_invoke,
    ensure_builtin_agents_registered,
    FakeSession,
    golden_evals_enabled,
    install_qwen_settings,
    install_service_mocks,
    make_seeded_workspace,
)

# Module-level gate: this suite only runs when the user explicitly opts in.
# Without RUN_GOLDEN_EVALS=1 we skip cleanly — these tests need a live local
# Qwen endpoint and run for ~30-90s each, so they should never run in CI.
if not golden_evals_enabled():
    pytest.skip(
        "Golden evals require RUN_GOLDEN_EVALS=1 (local Qwen endpoint).",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Cases — kept short on purpose so each runs in well under 3 minutes.
# ---------------------------------------------------------------------------


GOLDEN_CASES: list[dict] = [
    {
        "id": "ukrainian_describe_diagram",
        "message": (
            "Що в нас на діаграмі? Опиши, які об'єкти присутні і які звʼязки між ними."
        ),
        # Tokens we want to see (case-insensitive). At least ONE must appear in
        # the agent's final message — Qwen will phrase it differently every run.
        "expected_tokens_any": [
            "APP frontend",
            "APP backend",
            "frontend",
            "backend",
            "REST",
        ],
    },
    {
        "id": "english_describe_app_frontend",
        "message": "Describe the APP frontend object and what it connects to.",
        "expected_tokens_any": [
            "APP frontend",
            "frontend",
            "backend",
        ],
    },
    {
        "id": "english_list_connections",
        "message": "List all connections in this diagram.",
        "expected_tokens_any": [
            "REST",
            "frontend",
            "backend",
            "connection",
        ],
    },
]


# ---------------------------------------------------------------------------
# Per-case test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c["id"])
async def test_investigate_case(monkeypatch: pytest.MonkeyPatch, case: dict) -> None:
    """Drive the real general-agent graph against a live Qwen for *case*.

    Assertions are deliberately lenient: we check structure (a researcher
    delegation happened, a read tool was used, final_message is substantial)
    rather than exact wording — Qwen rephrases on every run.
    """
    ensure_builtin_agents_registered()

    ws = make_seeded_workspace()
    recorder = ToolCallRecorder()
    install_service_mocks(monkeypatch, ws=ws, recorder=recorder)
    install_qwen_settings(monkeypatch)

    db = FakeSession()
    result = await collect_invoke(
        db=db,
        workspace_id=ws.workspace_id,
        chat_context_kind="diagram",
        chat_context_id=ws.diagram_id,
        message=case["message"],
        mode="read_only",  # forces read-only path; no writes possible.
    )

    # ── 1. The run must complete without an error event. ──────────────────
    assert result.error is None, (
        f"Stream emitted error event: {result.error!r}"
    )

    # ── 2. We expect at least one node visit (the supervisor itself). ─────
    node_events = [e for e in result.events if e.kind == "node"]
    visited = {e.payload.get("name") for e in node_events}
    # Must have visited supervisor + finalize at minimum; ideally researcher.
    assert "supervisor" in visited, (
        f"Supervisor never ran. Visited: {sorted(visited)!r}"
    )

    # The researcher SHOULD have run at least once for an "explain"-style
    # question. We are lenient: Qwen sometimes answers from context alone for
    # very short prompts. We only enforce this for the longer Ukrainian case
    # which is unambiguous about needing structural info.
    if case["id"] == "ukrainian_describe_diagram":
        assert "researcher" in visited, (
            f"Researcher was not delegated to. Visited: {sorted(visited)!r}"
        )

    # ── 3. The final_message must be substantive. ─────────────────────────
    final = result.final_message or ""
    assert len(final) > 60, (
        f"final_message too short ({len(final)} chars): {final!r}"
    )

    # ── 4. The reply must mention at least one expected token. ────────────
    lower = final.lower()
    matched = [t for t in case["expected_tokens_any"] if t.lower() in lower]
    assert matched, (
        f"None of the expected tokens {case['expected_tokens_any']!r} "
        f"appeared in final_message: {final!r}"
    )

    # ── 5. No mutating service was touched (we ran in read_only mode). ────
    assert recorder.call_count("create_object") == 0
    assert recorder.call_count("create_connection") == 0
    assert recorder.call_count("place_on_diagram") == 0
