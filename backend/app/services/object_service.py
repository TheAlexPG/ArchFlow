import re
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.activity_log import ActivityTargetType
from app.models.connection import Connection
from app.models.diagram import DiagramObject
from app.models.object import ModelObject, ObjectType
from app.models.technology import Technology
from app.schemas.object import ObjectCreate, ObjectUpdate
from app.services import activity_service


# Object types that may carry a GitHub repo link. Mirrors the C4 model:
# `system` is C4 System, `app`/`store` are C4 Containers (deployable units).
# Group is L2 conceptually but is just a logical bucket — repos do not
# attach to groups.
REPO_LINKABLE_TYPES: frozenset[ObjectType] = frozenset(
    {ObjectType.SYSTEM, ObjectType.APP, ObjectType.STORE}
)


class InvalidRepoUrlError(ValueError):
    """The supplied repo_url did not match an accepted GitHub URL format."""


class RepoLinkNotAllowedError(ValueError):
    """repo_url was set on an object whose type is not eligible for repo links."""


# https://github.com/{owner}/{name}, optional trailing slash, optional .git
_GITHUB_HTTPS_RE = re.compile(
    r"^https?://github\.com/([A-Za-z0-9][A-Za-z0-9-_.]*)/([A-Za-z0-9][A-Za-z0-9-_.]*?)(?:\.git)?/?$"
)
# git@github.com:{owner}/{name}.git
_GITHUB_SSH_RE = re.compile(
    r"^git@github\.com:([A-Za-z0-9][A-Za-z0-9-_.]*)/([A-Za-z0-9][A-Za-z0-9-_.]*?)(?:\.git)?$"
)


def normalize_repo_url(repo_url: str) -> tuple[str, str]:
    """Validate + normalise a GitHub URL into the canonical
    ``https://github.com/{owner}/{name}`` form.

    Returns the (canonical_url, "{owner}/{name}") tuple.
    Raises InvalidRepoUrlError on a mismatch.
    """
    candidate = repo_url.strip()
    if not candidate:
        raise InvalidRepoUrlError("repo_url is empty")
    m = _GITHUB_HTTPS_RE.match(candidate) or _GITHUB_SSH_RE.match(candidate)
    if m is None:
        raise InvalidRepoUrlError(
            "repo_url must look like https://github.com/{owner}/{name} or "
            "git@github.com:{owner}/{name}.git"
        )
    owner, name = m.group(1), m.group(2)
    return f"https://github.com/{owner}/{name}", f"{owner}/{name}"


def _is_repo_linkable(obj_type: ObjectType | str | None) -> bool:
    """True iff the given object type may carry a repo_url."""
    if obj_type is None:
        return False
    value = getattr(obj_type, "value", obj_type)
    try:
        enum_val = ObjectType(value)
    except ValueError:
        return False
    return enum_val in REPO_LINKABLE_TYPES


async def validate_technology_ids(
    db: AsyncSession,
    workspace_id: uuid.UUID | None,
    ids: list[uuid.UUID] | None,
) -> None:
    """Verify every id in `ids` is visible to this workspace (built-in or
    workspace-owned). Raises ValueError listing the offenders on failure."""
    if not ids:
        return
    result = await db.execute(
        select(Technology.id).where(
            Technology.id.in_(ids),
            or_(
                Technology.workspace_id.is_(None),
                Technology.workspace_id == workspace_id,
            ),
        )
    )
    found = {row[0] for row in result.all()}
    missing = set(ids) - found
    if missing:
        raise ValueError(
            f"Unknown or cross-workspace technology_ids: {sorted(str(m) for m in missing)}"
        )


async def get_objects(
    db: AsyncSession,
    type_filter: str | None = None,
    status_filter: str | None = None,
    parent_id: uuid.UUID | None = None,
    draft_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> list[ModelObject]:
    query = select(ModelObject)
    # Live queries hide draft-scoped objects. When a draft_id is passed we
    # include that draft's forked objects AND the live model, because a
    # forked diagram can reference either.
    if draft_id is not None:
        query = query.where(
            (ModelObject.draft_id.is_(None)) | (ModelObject.draft_id == draft_id)
        )
    else:
        query = query.where(ModelObject.draft_id.is_(None))
    if workspace_id is not None:
        query = query.where(ModelObject.workspace_id == workspace_id)
    if type_filter:
        query = query.where(ModelObject.type == type_filter)
    if status_filter:
        query = query.where(ModelObject.status == status_filter)
    if parent_id:
        query = query.where(ModelObject.parent_id == parent_id)
    result = await db.execute(query.order_by(ModelObject.name))
    return list(result.scalars().all())


async def get_object(db: AsyncSession, object_id: uuid.UUID) -> ModelObject | None:
    result = await db.execute(select(ModelObject).where(ModelObject.id == object_id))
    return result.scalar_one_or_none()


class DuplicateObjectError(ValueError):
    """Raised by :func:`create_object` when a live (non-draft) object with the
    same ``(workspace_id, type, lower(name))`` already exists.

    Carries the existing :class:`ModelObject` so callers (e.g. the agent's
    ``create_object`` tool wrapper) can return its id instead of failing the
    whole turn — the right behaviour for "reuse, don't duplicate" semantics.
    """

    def __init__(self, existing: ModelObject) -> None:
        super().__init__(
            f"object already exists: name={existing.name!r} type={getattr(existing.type, 'value', existing.type)!r} "
            f"id={existing.id} (use that id with place_on_diagram instead)"
        )
        self.existing = existing


async def create_object(
    db: AsyncSession,
    data: ObjectCreate,
    draft_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> ModelObject:
    await validate_technology_ids(db, workspace_id, data.technology_ids)

    # Repo-link validation. Reject links on non-Container/System types up
    # front so the API surface returns 422 with a clear message.
    repo_url_normalized: str | None = None
    if data.repo_url is not None and data.repo_url.strip():
        if not _is_repo_linkable(data.type):
            raise RepoLinkNotAllowedError(
                "repo_url can only be set on System or Container "
                "(app/store) objects"
            )
        repo_url_normalized, _ = normalize_repo_url(data.repo_url)
    elif data.repo_branch is not None and data.repo_branch.strip():
        # A branch without a URL is a config error — surface it.
        raise InvalidRepoUrlError(
            "repo_branch requires repo_url to be set"
        )

    # Refuse silent duplicates on the live (non-draft) model. Drafts are
    # private workspaces; same-name copies there are intentional. For live
    # creates we look for ``(workspace_id, type, lower(name))`` and raise
    # :class:`DuplicateObjectError` carrying the existing row so the caller
    # can reuse it.
    if draft_id is None and data.name and data.name.strip():
        type_value = getattr(data.type, "value", data.type)
        from sqlalchemy import func as _func

        existing_q = select(ModelObject).where(
            ModelObject.draft_id.is_(None),
            ModelObject.type == type_value,
            _func.lower(ModelObject.name) == data.name.strip().lower(),
        )
        if workspace_id is not None:
            existing_q = existing_q.where(ModelObject.workspace_id == workspace_id)
        existing_row = (await db.execute(existing_q.limit(1))).scalar_one_or_none()
        if existing_row is not None:
            raise DuplicateObjectError(existing_row)

    obj = ModelObject(
        name=data.name,
        type=data.type,
        scope=data.scope,
        status=data.status,
        description=data.description,
        icon=data.icon,
        parent_id=data.parent_id,
        technology_ids=data.technology_ids,
        tags=data.tags,
        owner_team=data.owner_team,
        external_links=data.external_links,
        metadata_=data.metadata_,
        repo_url=repo_url_normalized,
        repo_branch=(data.repo_branch.strip() or None) if data.repo_branch else None,
        draft_id=draft_id,
        workspace_id=workspace_id,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    # Only log activity for live objects; draft-scoped changes live
    # inside the draft until they're applied.
    if draft_id is None:
        await activity_service.log_created(
            db, ActivityTargetType.OBJECT, obj, workspace_id=workspace_id
        )

    # Undo recording — both live and draft creates record. Draft entries
    # land on the draft-scoped stack (cleaned up on draft discard/apply).
    if (
        actor_user is not None
        and from_diagram_id is not None
        and obj.workspace_id is not None
    ):
        from app.models.undo_entry import UndoAction, UndoTargetType
        from app.services import undo_service

        await undo_service.record(
            db,
            user_id=actor_user.id,
            workspace_id=obj.workspace_id,
            diagram_id=from_diagram_id,
            draft_id=from_draft_id,
            target_type=UndoTargetType.OBJECT,
            target_id=obj.id,
            action=UndoAction.CREATE,
            forward_summary=f"Created {(obj.name or '?')[:60]}"[:80],
            inverse_payload={"target_id": str(obj.id)},
            after_state=activity_service.snapshot(obj, include_metadata=True),
            coalesce_key=f"object:{obj.id}:create",
        )

    return obj


async def update_object(
    db: AsyncSession,
    obj: ModelObject,
    data: ObjectUpdate,
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> ModelObject:
    if "technology_ids" in data.model_fields_set:
        await validate_technology_ids(db, obj.workspace_id, data.technology_ids)

    # Compute the effective object type post-update — if the caller is
    # changing both type and repo_url in the same request, the new type
    # is what matters for the eligibility check.
    effective_type = data.type if "type" in data.model_fields_set else obj.type
    update_data = data.model_dump(exclude_unset=True)
    # Strip undo-context fields that are not object attributes
    update_data.pop("from_diagram_id", None)
    update_data.pop("from_draft_id", None)

    if "repo_url" in update_data:
        raw = update_data["repo_url"]
        if raw is not None and str(raw).strip():
            if not _is_repo_linkable(effective_type):
                raise RepoLinkNotAllowedError(
                    "repo_url can only be set on System or Container "
                    "(app/store) objects"
                )
            update_data["repo_url"], _ = normalize_repo_url(str(raw))
        else:
            # Empty / None clears the link AND the branch (a branch without
            # a URL is meaningless).
            update_data["repo_url"] = None
            if "repo_branch" not in update_data:
                update_data["repo_branch"] = None

    if "repo_branch" in update_data and update_data["repo_branch"] is not None:
        cleaned = str(update_data["repo_branch"]).strip()
        update_data["repo_branch"] = cleaned or None
        # Verify there's actually a URL after this update — either set in
        # this request or already on the row.
        effective_url = (
            update_data.get("repo_url", obj.repo_url)
            if "repo_url" in update_data
            else obj.repo_url
        )
        if update_data["repo_branch"] is not None and not effective_url:
            raise InvalidRepoUrlError(
                "repo_branch requires repo_url to be set"
            )

    # Two snapshot pairs: activity log keeps metadata out of audit diffs,
    # undo needs metadata to detect metadata-only edits and round-trip them.
    before_for_log = activity_service.snapshot(obj)
    before_for_undo = activity_service.snapshot(obj, include_metadata=True)
    for field, value in update_data.items():
        if field == "metadata_" and value and obj.metadata_:
            # Merge metadata instead of replacing
            merged = {**obj.metadata_, **value}
            setattr(obj, field, merged)
        else:
            setattr(obj, field, value)
    await db.flush()
    await db.refresh(obj)
    after_for_log = activity_service.snapshot(obj)
    after_for_undo = activity_service.snapshot(obj, include_metadata=True)
    await activity_service.log_updated(
        db, ActivityTargetType.OBJECT, obj.id, before_for_log, after_for_log,
        workspace_id=obj.workspace_id,
    )

    # Undo recording
    if (
        actor_user is not None
        and from_diagram_id is not None
        and obj.workspace_id is not None
    ):
        diff = activity_service.diff_snapshots(before_for_undo, after_for_undo)
        if diff:
            from app.models.undo_entry import UndoAction, UndoTargetType
            from app.services import undo_service

            await undo_service.record(
                db,
                user_id=actor_user.id,
                workspace_id=obj.workspace_id,
                diagram_id=from_diagram_id,
                draft_id=from_draft_id,
                target_type=UndoTargetType.OBJECT,
                target_id=obj.id,
                action=UndoAction.UPDATE,
                forward_summary=_summarise_object_diff(obj, diff),
                inverse_payload={"before": {k: v["before"] for k, v in diff.items()}},
                after_state={k: v["after"] for k, v in diff.items()},
                coalesce_key=f"object:{obj.id}:{','.join(sorted(diff.keys()))}",
            )

    return obj


async def delete_object(
    db: AsyncSession,
    obj: ModelObject,
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> None:
    # Capture snapshot and placements BEFORE delete. Undo needs the full row
    # (including metadata_) so restore_service can rebuild the entity; the
    # activity log keeps its no-metadata default via log_deleted itself.
    snapshot = activity_service.snapshot(obj, include_metadata=True)
    obj_id = obj.id
    obj_ws_id = obj.workspace_id

    # Capture DiagramObject placements so restore_service can replay them
    placements_result = await db.execute(
        select(DiagramObject).where(DiagramObject.object_id == obj_id)
    )
    placements = list(placements_result.scalars().all())
    if placements:
        snapshot["_placements"] = [
            activity_service.snapshot(p, include_metadata=True) for p in placements
        ]

    await activity_service.log_deleted(
        db, ActivityTargetType.OBJECT, obj, workspace_id=obj_ws_id
    )
    await db.delete(obj)
    await db.flush()

    # Undo recording
    if (
        actor_user is not None
        and from_diagram_id is not None
        and obj_ws_id is not None
    ):
        from app.models.undo_entry import UndoAction, UndoTargetType
        from app.services import undo_service

        await undo_service.record(
            db,
            user_id=actor_user.id,
            workspace_id=obj_ws_id,
            diagram_id=from_diagram_id,
            draft_id=from_draft_id,
            target_type=UndoTargetType.OBJECT,
            target_id=obj_id,
            action=UndoAction.DELETE,
            forward_summary=f"Deleted {(snapshot.get('name') or '?')[:60]}"[:80],
            inverse_payload={"snapshot": snapshot, "id": str(obj_id)},
            after_state=None,
            coalesce_key=f"object:{obj_id}:delete",
        )


async def get_children(db: AsyncSession, object_id: uuid.UUID) -> list[ModelObject]:
    result = await db.execute(
        select(ModelObject)
        .where(ModelObject.parent_id == object_id)
        .order_by(ModelObject.name)
    )
    return list(result.scalars().all())


async def get_dependencies(
    db: AsyncSession, object_id: uuid.UUID
) -> dict[str, list]:
    """Get upstream and downstream dependencies for an object."""
    upstream_q = await db.execute(
        select(Connection)
        .where(Connection.target_id == object_id)
        .options(selectinload(Connection.source))
    )
    downstream_q = await db.execute(
        select(Connection)
        .where(Connection.source_id == object_id)
        .options(selectinload(Connection.target))
    )
    return {
        "upstream": list(upstream_q.scalars().all()),
        "downstream": list(downstream_q.scalars().all()),
    }


def _summarise_object_diff(obj: ModelObject, diff: dict) -> str:
    """Human-readable label for the history popover. Max ~80 chars."""
    fields = ", ".join(sorted(diff.keys()))
    name = (obj.name or "?")[:40]
    return f"Edited {name} — {fields}"[:80]
