"""Persist + replay SSE event streams for chat reconnect.

Backed by a Redis stream per chat session so a client that drops mid-flight
can resume via ``GET /api/v1/agents/sessions/{id}/stream?since=N`` (task 037).

Stream key layout::

    agent_events:{session_id}        (a Redis Stream — XADD/XRANGE/XLEN)

Each entry stores:
    kind     — SSE event kind (e.g. ``session``, ``token``, ``done``)
    event_id — sequential int assigned by the chat endpoint (matches the
               wire ``id:`` field, so the client's ``Last-Event-ID`` header
               maps directly to ``since`` here)
    data     — JSON-encoded payload dict

TTL: kept "forever" while the run is in progress.  After the terminal
``done`` event the producer calls :func:`finalize_stream` which sets a
5-minute expiry — long enough to absorb a network hiccup but short enough
that idle keys don't accumulate in Redis.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Hard cap on stream size to bound memory in case a runaway agent emits
# millions of token events.  ~1k events is plenty for reconnect; older
# entries get trimmed by Redis.
_STREAM_MAXLEN = 1000

# TTL applied after the terminal ``done`` event lands.  Five minutes mirrors
# the spec window for reconnect support (§5.4).
TTL_SECONDS = 300


def stream_key(session_id: UUID | str) -> str:
    """Return the Redis stream key for *session_id*."""
    return f"agent_events:{session_id}"


async def append_event(
    redis: Any,
    session_id: UUID | str,
    event_id: int,
    kind: str,
    payload: dict,
) -> None:
    """XADD a single SSE event into the session's Redis stream.

    Best-effort: failures are logged but never raised — losing the replay
    log must not abort the live SSE response.
    """
    try:
        await redis.xadd(
            stream_key(session_id),
            {
                "event_id": str(event_id),
                "kind": kind,
                "data": json.dumps(payload, default=str),
            },
            maxlen=_STREAM_MAXLEN,
            approximate=True,
        )
    except Exception:  # noqa: BLE001 — Redis outage shouldn't break the live stream
        logger.warning(
            "agent_event_log: append_event failed for session=%s event_id=%s kind=%s",
            session_id,
            event_id,
            kind,
            exc_info=True,
        )


async def replay_since(
    redis: Any,
    session_id: UUID | str,
    since_id: int,
) -> AsyncIterator[tuple[int, str, dict]]:
    """Async-yield ``(event_id, kind, payload)`` tuples after *since_id*.

    Reads via ``XRANGE`` (full scan, oldest→newest) and filters in Python
    so we don't depend on the Redis stream's internal ms-based IDs matching
    our sequential ``event_id`` field.  The volume per session is bounded
    by ``_STREAM_MAXLEN`` so this is fine.
    """
    key = stream_key(session_id)
    try:
        entries = await redis.xrange(key)
    except Exception:  # noqa: BLE001
        logger.warning(
            "agent_event_log: replay_since read failed for session=%s",
            session_id,
            exc_info=True,
        )
        return

    for _redis_id, fields in entries:
        try:
            event_id = int(fields.get("event_id", -1))
        except (TypeError, ValueError):
            continue
        if event_id <= since_id:
            continue
        kind = fields.get("kind") or ""
        raw = fields.get("data") or "{}"
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            payload = {"_raw": raw}
        if not isinstance(payload, dict):
            payload = {"value": payload}
        yield event_id, kind, payload


async def finalize_stream(redis: Any, session_id: UUID | str) -> None:
    """Set the 5-minute TTL on the session stream after the terminal ``done`` event."""
    try:
        await redis.expire(stream_key(session_id), TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning(
            "agent_event_log: finalize_stream expire failed for session=%s",
            session_id,
            exc_info=True,
        )
