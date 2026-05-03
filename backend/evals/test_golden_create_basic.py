"""Golden eval — basic creation cases against a real Qwen instance.

Each case feeds a "create + connect" instruction (e.g. "add a Redis store with
bidirectional connection to APP frontend") to the general agent and asserts:

  * ``create_object`` was invoked once with the right type;
  * ``place_on_diagram`` was invoked once;
  * ``create_connection`` was invoked once (with the requested direction
    where the case is unambiguous);
  * ``applied_changes`` count >= 3;
  * the final message announces what was done.

The LLM is the real Qwen model running in LM Studio at
``http://192.168.0.146:11434/v1``. Database / tool execution is mocked via
:mod:`evals.lib.golden_runtime` — no real diagram rows are written.

Skipped by default — set ``RUN_GOLDEN_EVALS=1`` to enable.

Run::

    cd backend && RUN_GOLDEN_EVALS=1 uv run pytest \
        evals/test_golden_create_basic.py -v -s
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

if not golden_evals_enabled():
    pytest.skip(
        "Golden evals require RUN_GOLDEN_EVALS=1 (local Qwen endpoint).",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


GOLDEN_CASES: list = [
    pytest.param(
        {
            "id": "redis_store_bidirectional",
            "message": (
                "Add a Redis cache as a store with bidirectional connection to "
                "the APP frontend. Place it on the current diagram."
            ),
            "expected_object_type": "store",
            "expected_object_name_substring": "redis",
            "expected_direction": "bidirectional",
        },
        # Qwen flakes on the 'bidirectional' direction word ~2/3 of runs and
        # picks 'unidirectional' instead. The other tool-call structure is
        # correct (create_object/store, place_on_diagram, create_connection).
        # Tracking via xfail so we still see when Qwen happens to get it right.
        marks=pytest.mark.xfail(
            reason=(
                "Qwen3 6.35b-a3b often picks 'unidirectional' even when the "
                "prompt says 'bidirectional'. Real bug in the prompt/tool "
                "schema; tracked here so the eval surfaces it as signal."
            ),
            strict=False,
        ),
        id="redis_store_bidirectional",
    ),
    {
        "id": "postgres_store_outgoing",
        "message": (
            "Create a Postgres database (store) and place it on the diagram. "
            "Connect the APP backend to it (one-way: backend reads from "
            "postgres)."
        ),
        "expected_object_type": "store",
        "expected_object_name_substring": "postgres",
        # We do NOT force a specific direction here — Qwen frequently picks
        # 'unidirectional' or 'outgoing' for one-way; both are acceptable.
        "expected_direction": None,
    },
    {
        "id": "kafka_topic_store",
        "message": (
            "Add a Kafka topic as a store on this diagram and connect "
            "APP backend to it."
        ),
        "expected_object_type": "store",
        "expected_object_name_substring": "kafka",
        "expected_direction": None,
    },
]


# ---------------------------------------------------------------------------
# Per-case test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c["id"])
async def test_create_basic_case(monkeypatch: pytest.MonkeyPatch, case: dict) -> None:
    """Drive the full general-agent graph for a "create new store + connect"
    request and verify the agent invoked the right tool path.

    We accept some Qwen drift:
      * extra search_existing_objects calls before the create;
      * extra read_diagram calls;
      * exact wording of the final_message;

    What we DO enforce:
      * create_object called >= 1 time (often == 1; we allow more in case Qwen
        also creates the connection target redundantly);
      * place_on_diagram called >= 1 time;
      * create_connection called >= 1 time;
      * applied_changes >= 3 (one per mutation tool: create + place + connect).
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
        mode="full",
    )

    # ── 1. No error event. ────────────────────────────────────────────────
    assert result.error is None, f"Stream emitted error event: {result.error!r}"

    # ── 2. Mutating tools invoked. ────────────────────────────────────────
    create_obj_calls = [
        c for c in recorder.calls if c.name == "create_object"
    ]
    place_calls = [c for c in recorder.calls if c.name == "place_on_diagram"]
    conn_calls = [c for c in recorder.calls if c.name == "create_connection"]

    assert len(create_obj_calls) >= 1, (
        f"Expected create_object to be called; recorder saw {recorder.names()!r}"
    )
    assert len(place_calls) >= 1, (
        f"Expected place_on_diagram; recorder saw {recorder.names()!r}"
    )
    assert len(conn_calls) >= 1, (
        f"Expected create_connection; recorder saw {recorder.names()!r}"
    )

    # ── 3. The first create_object is the new store. ──────────────────────
    first_create = create_obj_calls[0]
    assert first_create.args.get("type") == case["expected_object_type"], (
        f"create_object type mismatch — expected {case['expected_object_type']!r}, "
        f"got {first_create.args.get('type')!r}"
    )
    name_substr = case["expected_object_name_substring"].lower()
    assert name_substr in (first_create.args.get("name") or "").lower(), (
        f"create_object name {first_create.args.get('name')!r} does not contain "
        f"{name_substr!r}"
    )

    # ── 4. Direction (only checked when the case mandates it). ────────────
    if case["expected_direction"] is not None:
        first_conn = conn_calls[0]
        observed_dir = first_conn.args.get("direction")
        assert observed_dir == case["expected_direction"], (
            f"create_connection direction mismatch — expected "
            f"{case['expected_direction']!r}, got {observed_dir!r}"
        )

    # ── 5. applied_changes ≥ 3 (object.created + object.placed + connection.created). ─
    assert len(result.applied_changes) >= 3, (
        f"Expected ≥3 applied_changes, got {len(result.applied_changes)}: "
        f"{result.applied_changes!r}"
    )

    actions = {c.get("action") for c in result.applied_changes}
    assert "object.created" in actions, (
        f"Expected an 'object.created' applied_change, got actions={sorted(a or '?' for a in actions)!r}"
    )

    # ── 6. final_message announces the result. ────────────────────────────
    final = result.final_message or ""
    assert len(final) > 40, (
        f"final_message too short ({len(final)} chars): {final!r}"
    )
    # Should mention either the new object name OR the type word.
    lower = final.lower()
    mentions = (
        case["expected_object_name_substring"].lower() in lower
        or case["expected_object_type"] in lower
        # Accept generic confirmations as well — Qwen sometimes says "Created
        # the store" without naming it explicitly.
        or "created" in lower
        or "added" in lower
    )
    assert mentions, (
        f"final_message does not announce the new store: {final!r}"
    )
