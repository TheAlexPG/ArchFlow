# Per-user Undo for the Diagram Canvas — Design

**Date:** 2026-05-04
**Status:** Spec — pending implementation plan
**Scope:** Diagram canvas only (objects, connections, diagram-object placements, edge properties, optionally comments). Out of scope: workspace settings, technology catalog, team/invite/auth flows.

---

## 1. Goal

Add per-user undo (and redo) to the ArchFlow diagram canvas. Each user has their own undo stack, scoped per-diagram and separately per-draft, persisted server-side so it survives refresh and syncs across the user's tabs/devices. The feature targets parity with industry standards (Figma, tldraw, Excalidraw) while respecting ArchFlow's REST + Postgres + last-write-wins reality.

## 2. Decisions (consolidated)

| Decision | Value |
|---|---|
| Stack scope | Per-user, per-diagram, per-draft-context (live and each draft are separate stacks). Server-backed. |
| Coverage | All mutating canvas actions **except comments**. Per-user toggle (`undo_settings.include_comments_in_undo`) opts comments in. |
| Conflict semantics — Phase 1 | Naive inverse + Figma's redo-snapshot trick (capture *current* state into the redo entry at undo time, not the user's old "after" state). Last-write-wins via existing mutation pipeline. |
| Conflict semantics — Phase 2 (feature-flagged, not v1) | Stale detection per action: skip on geometry, block on structural / property edits. Requires `after_state` column included in v1 schema. |
| Coalescing | (a) Frontend wire-side debounce on inline rename / edge label edit (500ms idle). (b) Server-side coalesce window of ≤2s on `(user, diagram, draft, target_type, target_id, field)`. |
| Drafts | Live and draft each have their own stack (`draft_id` column, NULL = live). On draft discard or merge, the draft's entries are deleted; the live stack is untouched. |
| Capacity | Last 100 entries OR last 3 days, whichever comes first. Cap enforced on insert (oldest evicted). 3-day window enforced lazily on read + nightly hard-delete sweeper. |
| Redo lifecycle | Cleared on any new mutation by the same user in the same context (standard editor behavior). |
| Keybinds | `Cmd/Ctrl+Z` undo · `Cmd/Ctrl+Shift+Z` redo · `Ctrl+Y` redo (Windows). Disabled when focus is in an input / textarea / contentEditable. |
| UI surface | Toolbar undo/redo buttons + history popover with click-to-undo-to-point. |
| Cross-tab visual sync | Comes free via existing realtime fanout: undo applies through normal mutation paths, fanout updates all clients. New `user.undo` / `user.redo` events on the per-user channel advance the stack cursor in the originating user's other tabs. |
| Optimistic undo | **No.** Wait for server response before re-rendering. The inverse depends on server state the client can't reliably predict. |

## 3. Architecture

The undo stack is **server-side**. The frontend holds a cursor + denormalized cache for the popover labels.

### Single-undo dataflow

```
Cmd+Z in tab 1
    │
    ▼
useUndoController              POST /api/v1/diagrams/{id}/undo
                               body: { draft_id?, expected_seq }
    │
    ▼
undo_service.undo(user, diagram, draft?)
    │
    ├ 1. Read top-of-active for (user, diagram, draft)
    ├ 2. Compute inverse mutation from entry.inverse_payload
    ├ 3. Snapshot CURRENT target state → entry.redo_payload  (Figma's trick)
    ├ 4. Apply inverse via existing mutation paths:
    │       update-undo  → service.update(...)             (existing)
    │       create-undo  → service.delete(...)             (existing)
    │       delete-undo  → service.restore(snapshot, id)   (NEW small path —
    │                                                       create-with-fixed-id +
    │                                                       child-row rebind)
    │      Same activity_log, ACL, WS fanout, validation all run unchanged.
    ├ 5. Mark entry state='undone', undone_at = now()
    └ 6. Emit `user.undo` WS event to caller's other tabs
    ▼
Standard `object.updated` etc. events fan out to all clients
React Query cache patches → canvas re-renders everywhere
```

**Key principle:** undo does NOT bypass the existing mutation pipeline. An undo of "Alice renamed X" is literally `update_object(name=old)` run by Alice. This means ACLs are checked, activity_log records the inverse normally, WebSocket fanout is unchanged, and other clients can't tell an undo from any other edit.

### New components

1. **`undo_entries` Postgres table** — one row per coalesced logical action.
2. **`undo_service`** in `backend/app/services/` — owns recording, coalescing, popping/pushing the cursor, cap enforcement, sweeper.
3. **Mutation-side hook** — one new line in each existing service mutation (`object_service.update`, `connection_service.create`, etc.) calling `undo_service.record(...)` after the DB write. Mirrors the existing `activity_service.log_*` line that's already there.

### What stays unchanged

- React Query mutations and optimistic updates
- WebSocket manager + Redis fanout
- `activity_log`
- ACL deps
- Canvas Zustand store (gets one new sibling store, no migration of existing state)

## 4. Data model

### New table: `undo_entries`

```
id                UUID PK
workspace_id      UUID FK → workspaces        -- denormalized for tenant-scoped sweeps and audit queries
user_id           UUID FK → users
diagram_id        UUID FK → diagrams
draft_id          UUID FK → drafts            -- NULLABLE; NULL = live diagram

seq               BIGINT                       -- monotonic per (user, diagram, draft); stack order

target_type       ENUM(object, connection, diagram_object, edge_property, comment)
target_id         UUID
action            ENUM(create, update, delete)

forward_summary   TEXT                         -- "Renamed 'Foo' → 'Payments DB'", ≤80 chars

inverse_payload   JSONB NOT NULL               -- to undo this entry, apply this
redo_payload      JSONB NULL                   -- captured AT UNDO TIME (Figma's trick)
after_state       JSONB NULL                   -- for Phase 2 stale detection (recorded but unused in v1)

coalesce_key      TEXT NOT NULL                -- "{target_type}:{target_id}:{field|action}"
state             ENUM(active, undone, skipped) NOT NULL DEFAULT active

created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at        TIMESTAMPTZ NOT NULL         -- bumped when coalescing extends entry
undone_at         TIMESTAMPTZ NULL

INDEX (user_id, diagram_id, draft_id, seq DESC)                                -- top-of-stack lookup
INDEX (user_id, diagram_id, draft_id, coalesce_key, updated_at DESC) WHERE state='active'  -- coalesce window
INDEX (workspace_id, created_at)                                               -- 3-day sweeper
INDEX (target_id, target_type)                                                 -- Phase 2 stale check
```

### Inverse payload shapes

| `action` | `inverse_payload` | Applied on undo by |
|---|---|---|
| `update` | `{ "before": { field: old_value, … } }` — only fields that actually changed | `service.update(target_id, **before)` |
| `create` | `{ "target_id": "…" }` | `service.delete(target_id)` |
| `delete` | `{ "snapshot": { full entity row + relations }, "id": "…" }` | A `restore(snapshot)` path that recreates with the same UUID and rebinds child rows (e.g. DiagramObject placements, connection protocol_ids) |

The full snapshot for delete is required because the C4 model lets the same object live on multiple diagrams — undo MUST recreate with the same UUID or every diagram referencing it breaks.

### Coalescing on insert

```
recent = SELECT *
         FROM undo_entries
         WHERE user_id = :u AND diagram_id = :d
           AND draft_id IS NOT DISTINCT FROM :draft
           AND coalesce_key = :ck
           AND state = 'active'
           AND updated_at > now() - INTERVAL '2 seconds'
         ORDER BY seq DESC LIMIT 1;

IF recent:
    -- Merge: inverse_payload STAYS at recent's value (= state before the very
    -- first edit in the window). Refresh updated_at and forward_summary.
    UPDATE undo_entries
        SET updated_at = now(), forward_summary = :new_summary
        WHERE id = recent.id;
ELSE:
    INSERT new entry; advance seq.
```

`coalesce_key` examples:
- `object:{id}:name` — typing in name field, all keystrokes coalesce
- `object:{id}:position` — drag-then-drop (multi-frame writes coalesce, but typically only one persisted write)
- `object:{id}:create` / `object:{id}:delete` — singletons, never coalesce
- `connection:{id}:label` — same pattern

Different fields on the same target → different keys → separate entries (matches user mental model). When a single mutation patches multiple fields atomically (e.g. sidebar "Save" updating name + status + tags together), the recording side composes a sorted-multi-field key — that batch coalesces with itself but not with single-field edits to one of those fields.

### Cap enforcement

After insert, evict beyond 100 for `(user, diagram, draft)`:

```sql
DELETE FROM undo_entries
WHERE id IN (
  SELECT id FROM undo_entries
  WHERE user_id = :u AND diagram_id = :d AND draft_id IS NOT DISTINCT FROM :draft
  ORDER BY seq DESC OFFSET 100
);
```

3-day window:
1. Reads filter `created_at > now() - INTERVAL '3 days'` (lazy).
2. Nightly sweeper hard-deletes anything older than 3 days. Reuses existing scheduler infra if present, otherwise a `make` target / cron entry.

### On draft discard or merge

```sql
DELETE FROM undo_entries WHERE draft_id = :did;
```

One statement, fired from the existing draft discard / merge service hook. Live stack (`draft_id IS NULL`) untouched.

### Migration

Single Alembic migration creating the table, the three enums (`undo_target_type`, `undo_state`, `undo_action`), and the four indexes. **No data backfill** — we do not retroactively populate from `activity_log` (would surprise users with a giant pre-existing stack on first deploy).

## 5. API surface

All four endpoints scoped under the diagram. Auth: standard JWT/API-key. ACL: caller must have `edit` access on the diagram.

### POST /api/v1/diagrams/{diagram_id}/undo

```
Query:    draft_id?: UUID
Body:     { expected_seq?: bigint }    -- optimistic-concurrency guard

200:      { undone_entry: {...}, remaining_undo_count, redo_count }
204:      stack empty (idempotent)
403:      no edit access
409:      expected_seq mismatch (caller refetches and retries)
410:      Phase 2 — top entry is stale (skip-on-geometry / block-on-structural)
```

### POST /api/v1/diagrams/{diagram_id}/redo

Symmetric. Same query / body / response shape (with `redone_entry`).

### GET /api/v1/diagrams/{diagram_id}/history

Drives the popover.

```
Query:    draft_id?: UUID, limit?: int = 50

200: {
  entries: [
    { id, seq, state, target_type, target_id, forward_summary,
      created_at, updated_at, undone_at }
  ],
  cursor_seq: bigint    // largest seq with state='active' = next-undoable
}
```

Returned in stack order (newest active first, then `state='undone'` redo entries below the cursor).

### POST /api/v1/diagrams/{diagram_id}/undo-to/{entry_id}

Click-to-undo-to-point. Server iterates entries until cursor lands at `entry_id`. Atomic in a single transaction — either all N steps succeed or none do.

```
Body:     { expected_path_length?: int }   -- 409 if mismatch
200:      { applied: [{ entry_id, direction: "undo"|"redo" }, ...], cursor_seq }
```

If a Phase-2 stale-block lands mid-batch, the entire transaction rolls back and returns 409 with the offending entry highlighted.

### WebSocket events

| Event | Channel | Recipients | Purpose |
|---|---|---|---|
| `user.undo` | per-user | caller's other tabs only | Advance stack cursor + popover state |
| `user.redo` | per-user | caller's other tabs only | Same |
| (existing) `object.updated`, `connection.deleted`, etc. | per-diagram | all clients | Visual sync — comes free via the inverse mutation passing through the normal pipeline |

No "this was an undo" flag on the entity events. Other clients render undos identically to edits.

### Recording-side hook (service layer, not REST)

Each existing mutation service gets one new line after the DB commit:

```python
async def update_object(db, user, object_id, patch, *, diagram_id, draft_id=None):
    before = await fetch_changed_fields(db, object_id, patch.keys())
    obj = await _do_update(db, object_id, patch)              # existing
    await activity_service.log_updated(...)                   # existing
    await fanout(...)                                         # existing
    await undo_service.record(                                # NEW
        db, user=user, diagram_id=diagram_id, draft_id=draft_id,
        target_type="object", target_id=object_id,
        action="update",
        before=before,
        forward_summary=summarize_object_diff(before, patch),
        coalesce_key=f"object:{object_id}:{','.join(sorted(patch.keys()))}",
    )
    return obj
```

Mutation sites to instrument (~14 total, all in `backend/app/services/`):
- `object_service`: create, update, delete
- `connection_service`: create, update, delete, flip
- `diagram_service`: add_object, remove_object, update_position, update_size
- `comment_service`: create, update, delete (only when caller's `include_comments_in_undo` is on)

### Configuration — user toggle

New column `users.undo_settings JSONB NOT NULL DEFAULT '{}'`. Currently:

```json
{ "include_comments_in_undo": false }
```

JSONB so we can grow without further migrations. Exposed via existing `PATCH /users/me`.

## 6. Frontend integration

### New files

| File | Purpose |
|---|---|
| `frontend/src/stores/undo-store.ts` | Zustand: `byContext: Record<ctxKey, { cursorSeq, undoCount, redoCount, recentEntries, isInFlight }>`. Per-context (`${diagramId}:${draftId ?? 'live'}`). |
| `frontend/src/hooks/use-undo.ts` | `useUndoController`, `useUndoMutation`, `useDiagramHistory`. |
| `frontend/src/components/canvas/UndoToolbarButtons.tsx` | Two buttons next to the canvas FAB; tooltip shows next entry's `forward_summary`; the undo button's `▾` opens the popover. |
| `frontend/src/components/canvas/HistoryPopover.tsx` | Single-column timeline, newest at top, cursor divider, click-to-undo-to-point. |

### Altered files

| File | Change |
|---|---|
| `frontend/src/components/canvas/ArchFlowCanvas.tsx` | Mount `useUndoController` + render the toolbar buttons (~10 lines) |
| `frontend/src/hooks/use-api.ts` | Add `useDebouncedMutation` (500ms idle) and apply it to the 3 inline-edit mutation sites |
| `frontend/src/hooks/use-realtime.ts` | Handle `user.undo` / `user.redo` events — call `undoStore.applyUserUndoEvent`. Do NOT re-apply the entity change; that comes via the existing `object.updated` etc. handlers. |
| `frontend/src/lib/api/orval.gen.ts` | Regenerated from OpenAPI |

### Wire-side debounce sites

| Mutation | Where | Debounce |
|---|---|---|
| Object name / label / description inline rename | `C4Node.tsx`, sidebar inputs | 500ms idle |
| Edge label inline edit | `C4Edge.tsx` | 500ms idle |
| Object resize | `ArchFlowCanvas.tsx` `onNodeResize` | already drop-only (verify, leave) |

Position drags already persist on `onNodeDragStop` only. No change.

### Keybind controller behavior

- Mounts at canvas level, unmounts on diagram unload (no global listener)
- Refuses to fire when focus is in `input` / `textarea` / `contentEditable` — so Cmd+Z in the rename field undoes the *text*, not the canvas
- Debounces double-press

### Popover layout

```
┌─────────────────────────────────────┐
│  My history · live diagram          │
│  ─────────────────────────────────  │
│  ↻ Renamed 'Foo' → 'Payments DB'    │  active, current
│  ↻ Moved Payments DB                │  active; click → undo 1 step
│  ↻ Created connection Web ↔ DB      │  active; click → undo 2 steps
│  ─── cursor ────────────────────    │
│  ↶ Resized Auth API                 │  undone (greyed); click → redo
│  ↶ Created Auth API                 │  undone; click → redo
│                                      │
│  Entries older than 3 days expire   │
└─────────────────────────────────────┘
```

Click on any entry → POST `/undo-to/{entry_id}` with `expected_path_length` = number of entries traversed. Server returns 409 if the stack changed under us; frontend refetches and re-renders.

### What stays out of v1

- Optimistic undo (we wait for the server)
- Undo for actions outside the diagram canvas
- Hover-preview of "what will Cmd+Z change?" (Phase 3 polish)
- Branching history trees (rejected)

## 7. Conflict handling & edge cases

### Phase 1 algorithm

```
undo(entry E):
    1. inverse_payload ← E.inverse_payload                      # already stored
    2. snapshot ← read current state of E.target_id             # fresh read
    3. E.redo_payload ← snapshot                                # Figma's trick
    4. apply inverse via existing service mutation              # last-write-wins
    5. E.state ← 'undone', E.undone_at ← now()
```

### Edge cases

1. **Target deleted by someone else.** Inverse mutation 404s. Catch → 410 Gone, mark `state='skipped'`, frontend toasts and recursively attempts the next entry (max 5 hops).
2. **ACL revoked.** Existing dep returns 403; stack untouched (preserved in case access restored).
3. **Live and draft stacks isolated.** Switching context shows that context's stack only; no bleed-through.
4. **Draft discarded / merged with redo entries pending.** `DELETE FROM undo_entries WHERE draft_id=:did`. Entries are gone — correct, since the draft no longer exists as a target context.
5. **Comments toggle flip mid-session.** Off→on: future comment mutations record entries; existing comments NOT retroactively added. On→off: stops recording but does NOT delete existing comment entries (user can still undo recent ones until they age out).
6. **Two tabs race the same Cmd+Z.** `expected_seq` guard: first wins, second 409s. Frontend on 409 refetches `/history`. Net effect: two distinct undos applied even though presses were near-simultaneous.
7. **`undo_service.record` itself fails after the mutation succeeded.** Log to Sentry, fall through silently. The mutation is NOT rolled back — activity_log already has the audit trail; a half-recorded undo entry would be a worse footgun than losing one stack entry.

### Phase 2 — stale detection (feature-flagged, post-v1)

Triggered by feature flag. Uses the `after_state` column already populated in v1.

```
undo(entry E) with stale-detection ON:
    current ← read current state of E.target_id
    is_stale ← compare(current, E.after_state)

    if is_stale:
        if E is geometry (position/size on object/diagram_object):
            E.state ← 'skipped'
            return undo(next entry)              # recursive, max 5 hops
        else:
            return 409 { code: "undo_stale_blocked", entry_id, current, after_state }
```

| Category | "Stale" definition | Phase 2 handling |
|---|---|---|
| Position / size | x/y/w/h drift > 1px | Skip + toast |
| Object property (name, status, technology, parent_id, …) | Any field in `after_state` doesn't match current | Block + toast |
| Connection structural (create, delete, flip, endpoint change) | Endpoint pair or existence differs | Block |
| Connection property (label, shape, protocols) | Matched fields differ | Block |
| `diagram_object` add/remove | Presence on diagram differs | Block |

Phase 2 ships as a feature-flag flip — no migration needed because `after_state` is in v1 schema.

## 8. Testing

### Backend (`pytest-asyncio`)

**Unit — `test_undo_service.py`:**
- `record()` row shape per (action, target_type)
- Coalescing: in-window same key → 1 row; out-of-window → 2 rows; different field → 2 rows; different user → 2 rows
- Cap eviction: insert #101 evicts #1; cap is per `(user, diagram, draft)` not global
- 3-day filter excludes old rows on read; sweeper hard-deletes them
- Inverse payload computed correctly per (action, target_type)
- `undo()` populates `redo_payload` from current state, not pre-action state
- `redo()` flips state back; subsequent new mutation clears redo entries
- Missing target → 410 + `state='skipped'`
- Comments toggle behavior (off / on / flip mid-session)

**Integration — `test_undo_endpoints.py`:**
- 403 without edit ACL
- 204 on empty stack
- 409 on `expected_seq` mismatch
- live vs draft scoping
- redo cleared after new action
- `/undo-to/{id}` is atomic; partial failure rolls back
- `user.undo` event on per-user channel; `object.updated` on diagram channel

**Multi-user scenarios — `test_collab_undo.py`** (the bug-catchers):
- Alice update X → Bob update X → Alice undo: Alice's PUT wins (Phase 1 LWW; assert explicitly so it doesn't regress when Phase 2 lands)
- Alice delete X → Alice undo: X recreated with same UUID, all DiagramObject placements restored
- Alice create connection W↔D → Bob delete D → Alice undo: 410, entry skipped
- Alice in two tabs Cmd+Z simultaneously: first wins, second 409, two distinct undos applied
- Draft merge while Alice's draft stack has redo entries: entries deleted, live stack untouched
- Phase 2 flag ON, geometry stale → skip + next entry attempted
- Phase 2 flag ON, structural stale → block with 409

**Migration:** up creates table + indexes; down drops them cleanly; no backfill expected.

### Frontend (Vitest + Testing Library)

**Unit:**
- `useUndoController` mounts/unmounts keybinds correctly
- Ignores Cmd+Z while focus in `input` / `textarea` / contentEditable
- `useDebouncedMutation` collapses keystrokes; flushes on blur
- `undo-store` state transitions on `setStackInfo` and `applyUserUndoEvent`

**Component:**
- `UndoToolbarButtons` reflects `canUndo` / `canRedo`; tooltip shows next entry's `forward_summary`
- `HistoryPopover` cursor divider position; click-to-here computes correct `expected_path_length`
- 409 from undo-to refetches and re-renders

**Integration (MSW):**
- Cmd+Z → POST /undo → mocked WS `object.updated` → canvas patches → button state updates
- Two-tab simulation: dispatch from tab A → assert tab B's store advances on `user.undo`

### Manual smoke checklist (CONTRIBUTING.md addendum)

- [ ] Cmd+Z in name-input field undoes text, not canvas
- [ ] Typing "Payments DB" then Cmd+Z reverts to original name (not 11 keystrokes back)
- [ ] Drag 3 objects in multi-select; Cmd+Z reverts all 3 in one press
- [ ] Same diagram in two tabs: undo in tab 1 visually updates tab 2
- [ ] Redo button greys out after any new action
- [ ] Comments toggle off → comment edit doesn't show in popover; toggle on → next comment edit shows
- [ ] History popover renders 50 entries smoothly; clicking item 25 traverses correctly

### Out of scope for tests

- Load-testing 10k+ entries/user (cap of 100 makes this irrelevant)
- Cross-browser keybind quirks (covered by existing canvas keybinds)
- Undo for actions outside the diagram canvas

## 9. Phasing

**v1 (this design):**
- Schema (incl. `after_state` column for forward-compat)
- `undo_service` recording + coalescing + cap + sweeper
- 4 REST endpoints + 2 WS events
- Frontend store + controller + toolbar buttons + history popover
- Wire-side debounce on inline rename / edge label
- All tests above except the Phase-2-specific cases
- Comments toggle wired through

**Phase 2 (post-v1, feature-flagged):**
- Stale-detection logic in `undo_service.undo` (uses `after_state` already in v1)
- Phase-2 multi-user scenario tests
- Toast UX for skip / block

**Phase 3 (later, if asked):**
- Hover preview of what Cmd+Z will change
- Optimistic undo for trivial cases (e.g. position) where we can predict the inverse cheaply
