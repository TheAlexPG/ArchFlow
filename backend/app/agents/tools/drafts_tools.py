"""Drafts tools: fork live diagrams, list active drafts, discard.
NO merge tool — merge is manual via the existing UI."""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.tools.base import ToolContext, tool


class ForkDiagramToDraftInput(BaseModel):
    diagram_id: UUID
    draft_name: str | None = Field(None, max_length=255)


class ListActiveDraftsInput(BaseModel):
    diagram_id: UUID | None = None  # if given: drafts for this diagram only


class DiscardDraftInput(BaseModel):
    draft_id: UUID
    confirmed: bool = False


@tool(
    name="fork_diagram_to_draft",
    description=(
        "Fork the active live diagram into a new draft. ONLY call when the user EXPLICITLY asks "
        "('create a draft', 'fork this'). DO NOT call to be safe — the system handles "
        "draft policy automatically. "
        "After forking, the active_draft_id is set; subsequent mutating tool calls "
        "write to the draft."
    ),
    input_schema=ForkDiagramToDraftInput,
    permission="diagram:edit",
    permission_target="diagram",
    required_scope="agents:write",
    mutating=True,
)
async def fork_diagram_to_draft(args: ForkDiagramToDraftInput, ctx: ToolContext) -> dict:
    """Fork a live diagram into a new draft.

    Calls draft_service.fork_existing_diagram(db, diagram_id, DraftCreate(...), author_id).
    Returns action + view_change payload so the runtime emits an SSE view_change event.
    """
    from app.schemas.draft import DraftCreate
    from app.services import draft_service

    actor_id: UUID | None = getattr(ctx.actor, "id", None)
    base_diagram_id = args.diagram_id

    # Generate a default name when none provided.
    name = args.draft_name or f"Draft of {base_diagram_id}"

    draft_data = DraftCreate(name=name)
    draft, dd = await draft_service.fork_existing_diagram(
        ctx.db,
        source_diagram_id=base_diagram_id,
        draft_data=draft_data,
        author_id=actor_id,
    )

    draft_id: UUID = draft.id

    return {
        "action": "diagram.draft_created",
        "target_type": "diagram",
        "target_id": draft_id,
        "base_diagram_id": base_diagram_id,
        "name": draft.name,
        "forked_diagram_id": dd.forked_diagram_id,
        "preview": f"Created draft {draft.name!r}",
        "view_change": {
            "kind": "draft_created",
            "to": {
                "kind": "diagram",
                "id": str(base_diagram_id),
                "draft_id": str(draft_id),
            },
        },
    }


@tool(
    name="list_active_drafts",
    description="List drafts open by the current actor (optionally filtered by base diagram).",
    input_schema=ListActiveDraftsInput,
    permission="diagram:read",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def list_active_drafts(args: ListActiveDraftsInput, ctx: ToolContext) -> dict:
    """Return all OPEN drafts visible to the current actor.

    When args.diagram_id is set, filters to drafts containing that source diagram.
    """
    from app.models.draft import DraftStatus
    from app.services import draft_service

    actor_id: UUID | None = getattr(ctx.actor, "id", None)

    if args.diagram_id is not None:
        # Drafts containing this specific source diagram.
        rows = await draft_service.get_drafts_for_diagram(ctx.db, args.diagram_id)
        drafts_out = [
            {
                "draft_id": r["draft_id"],
                "name": r["draft_name"],
                "status": r["draft_status"],
                "base_diagram_id": r["source_diagram_id"],
                "forked_diagram_id": r["forked_diagram_id"],
            }
            for r in rows
        ]
    else:
        # All OPEN drafts in the workspace.
        all_drafts = await draft_service.list_drafts(ctx.db)
        open_drafts = [d for d in all_drafts if d.status == DraftStatus.OPEN]

        # If actor is a user, filter to drafts authored by this actor (or all
        # if actor_id is None — service key / admin use-case).
        if actor_id is not None:
            open_drafts = [
                d for d in open_drafts
                if d.author_id is None or d.author_id == actor_id
            ]

        drafts_out = []
        for draft in open_drafts:
            diagram_entries = [
                {
                    "source_diagram_id": str(dd.source_diagram_id),
                    "forked_diagram_id": str(dd.forked_diagram_id),
                }
                for dd in (draft.diagrams or [])
            ]
            drafts_out.append(
                {
                    "draft_id": str(draft.id),
                    "name": draft.name,
                    "status": draft.status.value,
                    "diagrams": diagram_entries,
                    "author_id": str(draft.author_id) if draft.author_id else None,
                }
            )

    return {
        "drafts": drafts_out,
        "count": len(drafts_out),
    }


@tool(
    name="discard_draft",
    description=(
        "Delete a draft (does NOT merge — merge is manual UI). "
        "First call without confirmed=True returns preview; "
        "second call with confirmed=True deletes."
    ),
    input_schema=DiscardDraftInput,
    permission="diagram:manage",
    permission_target="workspace",
    required_scope="agents:admin",
    mutating=True,
    deprecates_model=True,
    needs_confirmed_gate=True,
)
async def discard_draft(args: DiscardDraftInput, ctx: ToolContext) -> dict:
    """Discard a draft permanently.

    Without confirmed=True returns an awaiting_confirmation preview.
    With confirmed=True calls draft_service.discard_draft.
    """
    from app.services import draft_service

    draft = await draft_service.get_draft(ctx.db, args.draft_id)
    if draft is None:
        from app.agents.errors import AgentError
        raise AgentError(f"Draft {args.draft_id} not found")

    diagram_count = len(draft.diagrams or [])

    if not args.confirmed:
        return {
            "status": "awaiting_confirmation",
            "draft_id": str(args.draft_id),
            "name": draft.name,
            "diagram_count": diagram_count,
            "preview": (
                f"Discarding draft {draft.name!r} will permanently delete "
                f"{diagram_count} forked diagram(s). Call again with confirmed=True to proceed."
            ),
        }

    discarded = await draft_service.discard_draft(ctx.db, draft)

    return {
        "action": "diagram.draft_discarded",
        "target_type": "diagram",
        "target_id": args.draft_id,
        "name": discarded.name,
        "preview": f"Discarded draft {discarded.name!r}",
    }
