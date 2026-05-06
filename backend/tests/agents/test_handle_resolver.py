"""Tests for the DB-aware handle resolver."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.tools._handle_resolver import (
    refresh_handles_for_object_placement,
    resolve_handles_for_connection,
)


def _placement(object_id, x: float, y: float, w: float = 220.0, h: float = 120.0):
    return SimpleNamespace(
        object_id=object_id, position_x=x, position_y=y, width=w, height=h
    )


def _connection(*, source_id, target_id, source_handle=None, target_handle=None):
    obj = SimpleNamespace(
        id=uuid4(),
        source_id=source_id,
        target_id=target_id,
        source_handle=source_handle,
        target_handle=target_handle,
        draft_id=None,
    )
    return obj


@pytest.mark.asyncio
async def test_resolve_handles_for_connection_uses_shared_diagram(monkeypatch):
    """Both endpoints placed on the same diagram → handles derived from
    geometry."""
    src_id, tgt_id = uuid4(), uuid4()
    diagram_id = uuid4()
    diagram = SimpleNamespace(id=diagram_id)

    monkeypatch.setattr(
        "app.services.diagram_service.get_diagrams_containing_object",
        AsyncMock(return_value=[diagram]),
    )
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram_objects",
        AsyncMock(
            return_value=[
                _placement(src_id, x=0, y=200),
                _placement(tgt_id, x=400, y=210),  # right of source
            ]
        ),
    )

    sh, th = await resolve_handles_for_connection(
        db=object(), source_id=src_id, target_id=tgt_id
    )
    assert (sh, th) == ("right", "left")


@pytest.mark.asyncio
async def test_resolve_handles_returns_none_when_only_one_endpoint_placed(monkeypatch):
    src_id, tgt_id = uuid4(), uuid4()

    async def fake_get(_db, oid):
        # source is placed on diagram A, target placed on a different diagram.
        if oid == src_id:
            return [SimpleNamespace(id=uuid4())]
        return [SimpleNamespace(id=uuid4())]

    monkeypatch.setattr(
        "app.services.diagram_service.get_diagrams_containing_object",
        fake_get,
    )

    sh, th = await resolve_handles_for_connection(
        db=object(), source_id=src_id, target_id=tgt_id
    )
    assert sh is None and th is None


@pytest.mark.asyncio
async def test_resolve_handles_returns_none_when_endpoint_not_placed(monkeypatch):
    src_id, tgt_id = uuid4(), uuid4()

    monkeypatch.setattr(
        "app.services.diagram_service.get_diagrams_containing_object",
        AsyncMock(return_value=[]),
    )

    sh, th = await resolve_handles_for_connection(
        db=object(), source_id=src_id, target_id=tgt_id
    )
    assert sh is None and th is None


@pytest.mark.asyncio
async def test_refresh_handles_fills_in_null_handles(monkeypatch):
    """When the placed object has connections with null handles whose other
    endpoint is also placed on the same diagram, handles get auto-set."""
    placed_id = uuid4()
    other_id = uuid4()
    diagram_id = uuid4()

    conn = _connection(source_id=placed_id, target_id=other_id)
    deps = {"upstream": [], "downstream": [conn]}

    monkeypatch.setattr(
        "app.services.object_service.get_dependencies",
        AsyncMock(return_value=deps),
    )
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram_objects",
        AsyncMock(
            return_value=[
                _placement(placed_id, x=0, y=200),
                _placement(other_id, x=400, y=210),
            ]
        ),
    )
    update_call = AsyncMock(return_value=conn)
    monkeypatch.setattr(
        "app.services.connection_service.update_connection", update_call
    )

    updated = await refresh_handles_for_object_placement(
        db=object(), diagram_id=diagram_id, object_id=placed_id
    )

    assert len(updated) == 1
    assert update_call.await_count == 1
    # Inspect the ConnectionUpdate that was passed.
    update_arg = update_call.await_args.args[2]
    assert update_arg.source_handle == "right"
    assert update_arg.target_handle == "left"


@pytest.mark.asyncio
async def test_refresh_handles_skips_connections_already_set(monkeypatch):
    """A connection that already has BOTH handles must not be touched —
    user/agent override wins."""
    placed_id = uuid4()
    other_id = uuid4()
    diagram_id = uuid4()

    conn = _connection(
        source_id=placed_id,
        target_id=other_id,
        source_handle="top",
        target_handle="bottom",
    )

    monkeypatch.setattr(
        "app.services.object_service.get_dependencies",
        AsyncMock(return_value={"upstream": [conn], "downstream": []}),
    )
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram_objects",
        AsyncMock(
            return_value=[
                _placement(placed_id, x=0, y=200),
                _placement(other_id, x=400, y=210),
            ]
        ),
    )
    update_call = AsyncMock()
    monkeypatch.setattr(
        "app.services.connection_service.update_connection", update_call
    )

    updated = await refresh_handles_for_object_placement(
        db=object(), diagram_id=diagram_id, object_id=placed_id
    )
    assert updated == []
    assert update_call.await_count == 0


@pytest.mark.asyncio
async def test_refresh_handles_skips_connection_with_endpoint_off_diagram(monkeypatch):
    placed_id = uuid4()
    other_id = uuid4()
    diagram_id = uuid4()

    conn = _connection(source_id=placed_id, target_id=other_id)
    monkeypatch.setattr(
        "app.services.object_service.get_dependencies",
        AsyncMock(return_value={"upstream": [], "downstream": [conn]}),
    )
    # Only the placed object is on this diagram — other endpoint is missing.
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram_objects",
        AsyncMock(return_value=[_placement(placed_id, x=0, y=200)]),
    )
    update_call = AsyncMock()
    monkeypatch.setattr(
        "app.services.connection_service.update_connection", update_call
    )

    updated = await refresh_handles_for_object_placement(
        db=object(), diagram_id=diagram_id, object_id=placed_id
    )
    assert updated == []
    assert update_call.await_count == 0
