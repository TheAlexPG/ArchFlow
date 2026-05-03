"""Shared scaffolding for the live "golden" agent eval suite.

These tests run the full general-agent graph via :func:`app.agents.runtime.stream`
against a real local Qwen instance (LM Studio) while MOCKING the database and
service-layer functions so no real diagram rows are written. The scaffolding
here provides:

* A seeded in-memory workspace (one diagram, two objects, one connection).
* A :class:`FakeSession` compatible with :mod:`app.agents.runtime` (handles
  session/message persistence + the SELECTs the runtime issues).
* Service-layer monkeypatch helpers that capture every mutating call into a
  :class:`ToolCallRecorder` so assertions can verify the agent invoked the
  expected tool path (``create_object`` once with type=store, etc.).

The LLM is NEVER mocked — that's the whole point of the suite. We want to
detect when prompts/graph cause Qwen to misbehave.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

# ---------------------------------------------------------------------------
# Endpoint constants — mirror scripts/smoke_test_agents.py.
# ---------------------------------------------------------------------------

LM_STUDIO_BASE = os.environ.get(
    "GOLDEN_EVAL_BASE_URL", "http://192.168.0.146:11434/v1"
)
QWEN_MODEL = os.environ.get("GOLDEN_EVAL_MODEL", "qwen/qwen3.6-35b-a3b")


# ---------------------------------------------------------------------------
# Seeded workspace
# ---------------------------------------------------------------------------


@dataclass
class SeededWorkspace:
    """In-memory canonical fixture: one diagram, two objects, one connection.

    Object IDs / diagram IDs are stable so prompts can mention them by name and
    the agent's tool calls can be deterministically resolved by the mocked
    services (every lookup returns the seeded row).
    """

    workspace_id: UUID = field(default_factory=lambda: UUID("00000000-0000-0000-0000-000000000001"))
    diagram_id: UUID = field(default_factory=lambda: UUID("00000000-0000-0000-0000-000000000010"))
    diagram_name: str = "L2 Container — APP"

    frontend_id: UUID = field(default_factory=lambda: UUID("00000000-0000-0000-0000-000000000020"))
    frontend_name: str = "APP frontend"

    backend_id: UUID = field(default_factory=lambda: UUID("00000000-0000-0000-0000-000000000021"))
    backend_name: str = "APP backend"

    connection_id: UUID = field(default_factory=lambda: UUID("00000000-0000-0000-0000-000000000030"))
    connection_label: str = "REST"


def make_seeded_workspace() -> SeededWorkspace:
    """Return a fresh seeded workspace (each test gets its own copy)."""
    return SeededWorkspace()


# ---------------------------------------------------------------------------
# FakeSession — minimal AsyncSession stand-in for runtime.stream(...)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """In-memory AsyncSession stand-in.

    Stores ``AgentChatSession`` and ``AgentChatMessage`` rows added via
    ``add()``; every other ``execute()`` returns an empty result. The runtime's
    ``_load_existing_messages`` swallows exceptions, so we don't need a fancy
    where-clause walker — empty results are interpreted as "no chat history".
    """

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def execute(self, stmt: Any):  # noqa: ARG002
        # The runtime's two SELECTs (load_or_create_session, load_existing_messages)
        # both tolerate empty results. resolve_for_agent also tolerates them.
        return _FakeResult([])

    async def delete(self, obj: Any) -> None:  # noqa: ARG002
        return None

    async def refresh(self, obj: Any) -> None:  # noqa: ARG002
        return None


# ---------------------------------------------------------------------------
# ToolCallRecorder — capture mutating service calls for assertions.
# ---------------------------------------------------------------------------


@dataclass
class RecordedCall:
    name: str
    args: dict
    returned: Any = None


class ToolCallRecorder:
    """Records each monkeypatched service-layer call by name."""

    def __init__(self) -> None:
        self.calls: list[RecordedCall] = []

    def record(self, name: str, args: dict, returned: Any) -> None:
        self.calls.append(RecordedCall(name=name, args=args, returned=returned))

    def names(self) -> list[str]:
        return [c.name for c in self.calls]

    def call_count(self, name: str) -> int:
        return sum(1 for c in self.calls if c.name == name)

    def first(self, name: str) -> RecordedCall | None:
        for c in self.calls:
            if c.name == name:
                return c
        return None


# ---------------------------------------------------------------------------
# Service monkeypatches — read-side returns seeded rows; write-side records.
# ---------------------------------------------------------------------------


def _mk_object_row(*, id: UUID, name: str, type_value: str, workspace_id: UUID) -> Any:
    obj = MagicMock()
    obj.id = id
    obj.name = name
    obj.type = SimpleNamespace(value=type_value)
    obj.parent_id = None
    obj.description = f"Seeded {name}"
    obj.technology_ids = []
    obj.tags = []
    obj.owner_team = None
    obj.status = SimpleNamespace(value="live")
    obj.scope = SimpleNamespace(value="internal")
    obj.workspace_id = workspace_id
    obj.draft_id = None
    obj.c4_level = "L2"
    return obj


def _mk_placement(*, object_id: UUID, x: float = 64.0, y: float = 64.0) -> Any:
    p = MagicMock()
    p.object_id = object_id
    p.position_x = x
    p.position_y = y
    p.width = 220
    p.height = 120
    return p


def _mk_diagram_row(*, ws: SeededWorkspace) -> Any:
    d = MagicMock()
    d.id = ws.diagram_id
    d.name = ws.diagram_name
    d.type = SimpleNamespace(value="container")
    d.description = f"Container view for {ws.diagram_name}"
    d.scope_object_id = None
    d.workspace_id = ws.workspace_id
    d.draft_id = None
    d.objects = [
        _mk_placement(object_id=ws.frontend_id, x=64, y=64),
        _mk_placement(object_id=ws.backend_id, x=320, y=64),
    ]
    return d


def _mk_connection_row(*, ws: SeededWorkspace) -> Any:
    c = MagicMock()
    c.id = ws.connection_id
    c.source_id = ws.frontend_id
    c.target_id = ws.backend_id
    c.label = ws.connection_label
    c.protocol_ids = []
    c.direction = SimpleNamespace(value="unidirectional")
    c.draft_id = None
    return c


def install_service_mocks(
    monkeypatch: Any, *, ws: SeededWorkspace, recorder: ToolCallRecorder
) -> None:
    """Monkeypatch every read+write service used by the agent's tools.

    Read calls return seeded rows; write calls record their args into
    ``recorder`` and return canned objects so the agent can keep going. No row
    ever lands in the test DB.

    Also stubs the layout engine (``incremental_place``) to a fixed result so
    we don't need to hit ``app.agents.layout.engine`` either way.
    """
    seeded_objects: dict[UUID, Any] = {
        ws.frontend_id: _mk_object_row(
            id=ws.frontend_id,
            name=ws.frontend_name,
            type_value="app",
            workspace_id=ws.workspace_id,
        ),
        ws.backend_id: _mk_object_row(
            id=ws.backend_id,
            name=ws.backend_name,
            type_value="app",
            workspace_id=ws.workspace_id,
        ),
    }
    seeded_diagram = _mk_diagram_row(ws=ws)
    seeded_connection = _mk_connection_row(ws=ws)

    # ── object_service ────────────────────────────────────────────────────
    async def fake_get_object(_db: Any, object_id: UUID) -> Any:
        return seeded_objects.get(object_id)

    async def fake_get_dependencies(_db: Any, object_id: UUID) -> dict[str, list]:
        if object_id == ws.frontend_id:
            return {"upstream": [], "downstream": [seeded_connection]}
        if object_id == ws.backend_id:
            return {"upstream": [seeded_connection], "downstream": []}
        return {"upstream": [], "downstream": []}

    async def fake_get_objects(*_a: Any, **_kw: Any) -> list[Any]:
        return list(seeded_objects.values())

    async def fake_create_object(
        _db: Any, data: Any, draft_id: UUID | None = None, workspace_id: UUID | None = None
    ) -> Any:
        new_id = uuid4()
        type_value = (
            data.type.value if hasattr(data.type, "value") else str(data.type)
        )
        new_obj = _mk_object_row(
            id=new_id,
            name=data.name,
            type_value=type_value,
            workspace_id=workspace_id or ws.workspace_id,
        )
        seeded_objects[new_id] = new_obj
        recorder.record(
            "create_object",
            {
                "name": data.name,
                "type": type_value,
                "draft_id": draft_id,
                "workspace_id": workspace_id,
            },
            new_obj,
        )
        return new_obj

    monkeypatch.setattr("app.services.object_service.get_object", fake_get_object)
    monkeypatch.setattr(
        "app.services.object_service.get_dependencies", fake_get_dependencies
    )
    monkeypatch.setattr("app.services.object_service.get_objects", fake_get_objects)
    monkeypatch.setattr(
        "app.services.object_service.create_object", fake_create_object
    )
    # update/delete won't be hit by our golden cases but stub them defensively.
    async def _noop_async(*_a: Any, **_kw: Any) -> Any:
        return None

    monkeypatch.setattr(
        "app.services.object_service.update_object", _noop_async
    )
    monkeypatch.setattr(
        "app.services.object_service.delete_object", _noop_async
    )
    monkeypatch.setattr(
        "app.services.object_service.validate_technology_ids", _noop_async
    )
    monkeypatch.setattr(
        "app.services.activity_service.log_created", _noop_async
    )
    monkeypatch.setattr(
        "app.services.activity_service.log_updated", _noop_async
    )
    monkeypatch.setattr(
        "app.services.activity_service.log_deleted", _noop_async
    )

    # ── diagram_service ───────────────────────────────────────────────────
    async def fake_get_diagram(_db: Any, diagram_id: UUID) -> Any:
        if diagram_id == ws.diagram_id:
            return seeded_diagram
        return None

    async def fake_get_diagrams(*_a: Any, **kw: Any) -> list[Any]:
        return [seeded_diagram]

    async def fake_get_diagram_objects(_db: Any, diagram_id: UUID) -> list[Any]:
        if diagram_id == ws.diagram_id:
            return list(seeded_diagram.objects)
        return []

    async def fake_get_diagrams_containing_object(
        _db: Any, _object_id: UUID
    ) -> list[Any]:
        return [seeded_diagram]

    async def fake_add_object_to_diagram(
        _db: Any, diagram_id: UUID, data: Any
    ) -> Any:
        placement = _mk_placement(
            object_id=data.object_id,
            x=float(data.position_x),
            y=float(data.position_y),
        )
        seeded_diagram.objects.append(placement)
        recorder.record(
            "place_on_diagram",
            {
                "diagram_id": diagram_id,
                "object_id": data.object_id,
                "x": float(data.position_x),
                "y": float(data.position_y),
            },
            placement,
        )
        return placement

    async def fake_update_diagram_object(*_a: Any, **_kw: Any) -> Any:
        return _mk_placement(object_id=uuid4())

    async def fake_remove_object_from_diagram(*_a: Any, **_kw: Any) -> bool:
        return True

    async def fake_create_diagram(
        _db: Any, data: Any, workspace_id: UUID | None = None
    ) -> Any:
        new_id = uuid4()
        d = MagicMock()
        d.id = new_id
        d.name = data.name
        type_value = (
            data.type.value if hasattr(data.type, "value") else str(data.type)
        )
        d.type = SimpleNamespace(value=type_value)
        d.description = data.description
        d.scope_object_id = data.scope_object_id
        d.workspace_id = workspace_id or ws.workspace_id
        d.objects = []
        recorder.record(
            "create_diagram",
            {"name": data.name, "type": type_value, "workspace_id": workspace_id},
            d,
        )
        return d

    async def fake_update_diagram(*_a: Any, **_kw: Any) -> Any:
        return seeded_diagram

    async def fake_delete_diagram(*_a: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr("app.services.diagram_service.get_diagram", fake_get_diagram)
    monkeypatch.setattr("app.services.diagram_service.get_diagrams", fake_get_diagrams)
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram_objects", fake_get_diagram_objects
    )
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagrams_containing_object",
        fake_get_diagrams_containing_object,
    )
    monkeypatch.setattr(
        "app.services.diagram_service.add_object_to_diagram",
        fake_add_object_to_diagram,
    )
    monkeypatch.setattr(
        "app.services.diagram_service.update_diagram_object",
        fake_update_diagram_object,
    )
    monkeypatch.setattr(
        "app.services.diagram_service.remove_object_from_diagram",
        fake_remove_object_from_diagram,
    )
    monkeypatch.setattr(
        "app.services.diagram_service.create_diagram", fake_create_diagram
    )
    monkeypatch.setattr(
        "app.services.diagram_service.update_diagram", fake_update_diagram
    )
    monkeypatch.setattr(
        "app.services.diagram_service.delete_diagram", fake_delete_diagram
    )

    # ── connection_service ────────────────────────────────────────────────
    async def fake_get_connection(_db: Any, _id: UUID) -> Any:
        return seeded_connection

    async def fake_get_connections(*_a: Any, **_kw: Any) -> list[Any]:
        return [seeded_connection]

    async def fake_get_connections_between(
        _db: Any, _src: UUID, _tgt: UUID
    ) -> list[Any]:
        return []

    async def fake_create_connection(
        _db: Any, data: Any, draft_id: UUID | None = None
    ) -> Any:
        new_id = uuid4()
        direction_value = (
            data.direction.value
            if hasattr(data.direction, "value")
            else str(data.direction)
        )
        c = MagicMock()
        c.id = new_id
        c.source_id = data.source_id
        c.target_id = data.target_id
        c.label = data.label
        c.protocol_ids = list(data.protocol_ids or [])
        c.direction = SimpleNamespace(value=direction_value)
        c.draft_id = draft_id
        recorder.record(
            "create_connection",
            {
                "source_id": data.source_id,
                "target_id": data.target_id,
                "label": data.label,
                "direction": direction_value,
                "draft_id": draft_id,
            },
            c,
        )
        return c

    monkeypatch.setattr(
        "app.services.connection_service.get_connection", fake_get_connection
    )
    monkeypatch.setattr(
        "app.services.connection_service.get_connections", fake_get_connections
    )
    monkeypatch.setattr(
        "app.services.connection_service.get_connections_between",
        fake_get_connections_between,
    )
    monkeypatch.setattr(
        "app.services.connection_service.create_connection", fake_create_connection
    )
    monkeypatch.setattr(
        "app.services.connection_service.update_connection", _noop_async
    )
    monkeypatch.setattr(
        "app.services.connection_service.delete_connection", _noop_async
    )

    # ── access_service (always allow) ─────────────────────────────────────
    async def _allow(*_a: Any, **_kw: Any) -> bool:
        return True

    monkeypatch.setattr("app.services.access_service.can_read_diagram", _allow)
    monkeypatch.setattr("app.services.access_service.can_write_diagram", _allow)

    # ── layout engine — return a fixed PlacementResult ────────────────────
    async def fake_incremental_place(*, diagram_id, object_id, db):  # noqa: ARG001
        return SimpleNamespace(x=64.0, y=64.0, w=220.0, h=120.0)

    monkeypatch.setattr(
        "app.agents.layout.engine.incremental_place", fake_incremental_place
    )

    # ── draft / technology service stubs (defensive) ──────────────────────
    async def _empty_drafts(*_a: Any, **_kw: Any) -> list[dict]:
        return []

    monkeypatch.setattr(
        "app.services.draft_service.get_drafts_for_diagram", _empty_drafts
    )

    async def _empty_techs(*_a: Any, **_kw: Any) -> list[Any]:
        return []

    monkeypatch.setattr(
        "app.services.technology_service.list_technologies", _empty_techs
    )


# ---------------------------------------------------------------------------
# Settings monkeypatch — point the runtime at LM Studio.
# ---------------------------------------------------------------------------


def install_qwen_settings(monkeypatch: Any) -> None:
    """Patch ``resolve_for_agent`` and rate-limit pre-flight to:
      * point the runtime at the local Qwen / LM Studio endpoint;
      * skip Redis-backed rate limiting.
    """
    from app.services.agent_settings_service import (
        AGENT_DEFAULTS,
        ResolvedAgentSettings,
    )

    async def fake_resolve(_db: Any, workspace_id: UUID, agent_id: str):
        s = ResolvedAgentSettings(
            workspace_id=workspace_id,
            agent_id=agent_id,
            litellm_provider="custom",
            litellm_base_url=LM_STUDIO_BASE,
            litellm_model=QWEN_MODEL,
            litellm_context_window=32768,
            # Eval traces want LLM calls visible in Langfuse alongside
            # supervisor / sub-agent spans. The trace gets a ":eval" suffix via
            # ARCHFLOW_TRACE_NAME_SUFFIX so production traces stay filterable.
            analytics_consent="full",
            agent_edits_policy="live_only",  # avoid drafts-policy detours
        )
        defaults = AGENT_DEFAULTS.get(agent_id, {})
        if "turn_limit" in defaults:
            s.turn_limit = defaults["turn_limit"]
        if "budget_usd" in defaults:
            s.budget_usd = Decimal(str(defaults["budget_usd"]))
        return s

    monkeypatch.setattr("app.agents.runtime.resolve_for_agent", fake_resolve)

    async def _no_rate_limit(*_a: Any, **_kw: Any) -> None:
        return None

    monkeypatch.setattr("app.agents.runtime.check_and_consume", _no_rate_limit)

    # Suffix all Langfuse trace names with ":eval" so eval runs are filterable
    # in the Langfuse UI (search by name `agent:general:eval`). Read by both
    # AgentTracer (root trace) and LLMClient._build_langfuse_metadata
    # (per-generation trace_name).
    monkeypatch.setenv("ARCHFLOW_TRACE_NAME_SUFFIX", ":eval")


# ---------------------------------------------------------------------------
# Public helper: collect SSE events from a runtime.stream(...) call.
# ---------------------------------------------------------------------------


async def collect_invoke(
    *,
    db: Any,
    workspace_id: UUID,
    chat_context_kind: str = "diagram",
    chat_context_id: UUID | None = None,
    message: str,
    actor_id: UUID | None = None,
    mode: str = "full",
):
    """Drive ``runtime.stream(...)`` to completion and return ``(InvokeResult,
    list[SSEEvent])``.

    Mirrors :func:`app.agents.runtime.invoke` but additionally returns the raw
    event list so callers can assert on ``applied_change`` events as they were
    streamed (not just the final aggregate).
    """
    from app.agents.runtime import (
        ActorRef,
        ChatContext,
        InvokeRequest,
        SSEEvent,
        stream,
    )

    actor = ActorRef(
        kind="user",
        id=actor_id or uuid4(),
        workspace_id=workspace_id,
        agent_access="full",
    )
    req = InvokeRequest(
        agent_id="general",
        actor=actor,
        workspace_id=workspace_id,
        chat_context=ChatContext(
            kind=chat_context_kind,  # type: ignore[arg-type]
            id=chat_context_id,
        ),
        message=message,
        mode=mode,  # type: ignore[arg-type]
    )

    events: list[SSEEvent] = []
    final_message = ""
    applied_changes: list[dict] = []
    session_id: UUID | None = None
    error: dict | None = None

    async for ev in stream(req, db=db):
        events.append(ev)
        if ev.kind == "session":
            sid = ev.payload.get("session_id")
            if isinstance(sid, str):
                try:
                    session_id = UUID(sid)
                except ValueError:
                    pass
        elif ev.kind == "message":
            final_message = ev.payload.get("text", final_message)
        elif ev.kind == "applied_change":
            applied_changes.append(ev.payload)
        elif ev.kind == "error":
            error = ev.payload

    return SimpleNamespace(
        session_id=session_id,
        final_message=final_message,
        applied_changes=applied_changes,
        events=events,
        error=error,
    )


# ---------------------------------------------------------------------------
# Module-level skip helper.
# ---------------------------------------------------------------------------


def golden_evals_enabled() -> bool:
    """Return True when ``RUN_GOLDEN_EVALS=1`` is set in the environment."""
    return os.environ.get("RUN_GOLDEN_EVALS", "").lower() in ("1", "true", "yes")


def ensure_builtin_agents_registered() -> None:
    """Side-effect import + registration of all builtin agents and tools.

    Idempotent — safe to call from every test.
    """
    import app.agents.tools  # noqa: F401 — populates the tool registry
    from app.agents.builtin import register_builtin_agents

    register_builtin_agents()
