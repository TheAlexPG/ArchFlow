# GitHub Repo Researcher — Design

**Status**: design approved 2026-05-04, ready for implementation
**Branch**: `feat/github-repo-researcher`
**Owner**: @alexpremiumgame

Add the ability to link a GitHub repository to a Container or System node in an ArchFlow diagram, then ask the AI agent natural-language questions about the linked repo or have it generate Component diagrams from the code.

## 1. Concept

The repo-bound agent is a **universal text-worker**: it accepts a free-form task from the supervisor, reads from the linked repo using a fixed tool surface (GitHub REST API only — no cloning), and returns free-form text/markdown. The supervisor decides whether to relay the response to the user as a chatbot answer or feed it to the existing planner+diagram-agent for visualization.

Agents are **runtime-only instances** of a single `repo_researcher` LangGraph node. Per-turn, the runtime walks the active diagram + descendants, discovers repo links, and exposes each as a virtual delegation target visible to the supervisor (e.g. `repo:auth-service`). No new agent records in the registry; the manifest is rebuilt from diagram state every turn.

## 2. Data model

### Workspace token

- New column: `workspaces.github_token_encrypted` (bytea/text, nullable)
- Reuse the existing API-key encryption pattern from LLM provider keys (find in `backend/app/services/api_keys/` or wherever LLM provider keys are stored)
- Set / cleared via workspace settings UI; only workspace owners can mutate
- Validated on save by calling `GET https://api.github.com/user` with the token (must return 200)

### Object repo link

- Two new columns on the `objects` table:
  - `repo_url` (text, nullable)
  - `repo_branch` (text, nullable; falls back to repo's default branch)
- Validation in service layer: only `Container` and `System` object types may carry these fields; reject otherwise with 422
- Accepted URL formats: `https://github.com/{owner}/{name}` and `git@github.com:{owner}/{name}.git`
- `repo_url` is normalized server-side to `https://github.com/{owner}/{name}` for storage

### Per-turn manifest resolver

```python
def collect_repo_manifest(active_diagram_id: UUID, db: AsyncSession) -> list[RepoLink]:
    ...
```

Walks the diagram tree in BOTH directions from the active diagram, cycle-guarded, with the same 3-level cap (`MAX_DEPTH`) as `useDiagramBreadcrumbs` applied PER direction:

- **Up (ancestors)**: follows `Diagram.scope_object_id` → that object → the `DiagramObject` placement that contains it → its parent `Diagram.scope_object_id` → ... up to 3 hops. Surfaces the repo on the active diagram's parent scope_object (the canonical "user drilled INTO a Container with a linked repo" case).
- **Down (descendants)**: BFS over child diagrams via `Diagram.scope_object_id == ModelObject.id`, unchanged from D3 v1.

Returned ordering: ancestors closest-first, then active level, then descendants BFS. Total entries capped at `MAX_MANIFEST_ENTRIES=50` across both directions (after dedup-by-URL). Same repo URL appearing on both an ancestor and a descendant is aggregated to ONE delegation tool whose description lists both linked components.

```python
class RepoLink:
    node_id: UUID
    node_name: str
    node_type: Literal["Container", "System"]
    repo_url: str
    repo_branch: str | None
    depth: int               # ancestors: upward distance (1=parent, 2=grandparent, ...); descendants: BFS depth (0=active, 1=child, ...)
    is_ancestor: bool        # True when collected by the upward walk
```

## 3. Tool surface (MVP — 9 tools)

All tools authenticated via the workspace's `github_token`. Per-turn LRU cache keyed by `(owner, repo, ref, path)` to dedupe within one turn. Rate-limit handled by retry-with-backoff middleware (max 3 retries, exponential, capped at 30s).

| Tool | Description | Notes |
|---|---|---|
| `repo_get_metadata()` | Repo description, languages%, default branch, topics, stars | Lets the agent ground itself |
| `repo_read_readme()` | README content (rendered as markdown) | Convenience over read_file |
| `repo_list_tree(path?, depth=2)` | Directory listing | Depth-capped to avoid blowing context on monorepos; recursive only on explicit `depth` arg |
| `repo_read_file(path, offset?, limit?)` | File content | 50KB default cap; offset/limit for larger files |
| `repo_search_code(query)` | Substring code search via GitHub Search API | Limited to default branch (API constraint). Returns top 30 hits with snippet + path |
| `repo_read_issues(state="open"\|"closed"\|"all")` | Issue list with bodies | Page size 30 |
| `repo_read_pulls(state)` | PR list with bodies + diffstat | Page size 30 |
| `repo_read_commits(path?, since?)` | Commit list, optionally scoped to a path | Returns 30 most recent |
| `repo_read_diff(base, head)` | Diff between two refs | Cap at 100KB |

All tools take `repo_url` and `repo_branch` from the runtime context (injected by the dispatch layer); the LLM never types the URL.

## 4. Agent topology

New node `repo_researcher` lives in `backend/app/agents/builtin/general/nodes/repo_researcher.py`. Architecturally identical to the existing `researcher` node but:

- System prompt is parameterized: `repo_url`, `repo_branch`, `repo_node_name`, `repo_node_type` are injected by the runtime when the node is invoked
- Tool subset is the 9 tools above, NOT the internal-knowledge tools the existing researcher has
- Read-only by contract — no diagram-mutation tools allowed
- Returns free-form text/markdown to the supervisor (no Pydantic Findings schema; the worker is generic)

### Supervisor extension

When `collect_repo_manifest` returns non-empty, the supervisor's system prompt gets an extra block:

```
AVAILABLE REPO RESEARCHERS:
- repo:auth-service — Reads my-org/auth-service (the AuthService Container)
- repo:billing — Reads my-org/billing (the BillingSystem System)
```

The supervisor's `delegate(target)` tool's enum becomes dynamic: built-ins (`researcher`, `planner`, `diagram`, `critic`) plus one `repo:<slug>` per manifest entry. The slug is derived from the node name (kebab-cased, lower) with a fallback to `repo:<short-uuid>` if names collide.

Routing on `target = repo:<slug>`:

1. Runtime resolves the manifest entry by slug
2. Constructs `RuntimeContext { repo_url, repo_branch, repo_node_name, repo_node_type }`
3. Routes to `repo_researcher` LangGraph node with that context
4. Node's free-form text response is returned to the supervisor

The supervisor decides next step:
- Relay to user (chatbot Q&A use case)
- Forward to `planner` → `diagram` (visualize-this use case)
- Save to scratchpad for later reasoning

## 5. Error handling

| Condition | Behavior |
|---|---|
| Workspace has no token | Manifest is empty; repo features unavailable. Silent — no error to user, supervisor just doesn't see `repo:*` targets |
| Token invalid (401 from GitHub) | Non-blocking warning surfaced to chat; mark workspace as `needs_github_token_refresh`; manifest empty for the rest of the turn |
| Repo not found (404) | The specific repo target is omitted from the manifest; node UI shows "broken link" indicator; user prompted to update URL |
| Rate limit hit (403 with `X-RateLimit-Remaining: 0`) | Backoff retry up to 3x with exponential delay; if still hitting, return error result to supervisor and surface as warning |
| File > 50KB requested | Truncate at 50KB; include offset hint in the response so the LLM knows to request more |
| Cycle in diagram tree | Depth-cap at 3 (mirrors `useDiagramBreadcrumbs`'s existing guard) |

## 6. Frontend affordances

### Workspace settings

- Workspace settings page → new "GitHub" block
- Fields:
  - PAT input (type=password, with show/hide toggle)
  - "Test connection" button (calls a backend endpoint that hits `GET /user`)
  - "Clear" button
- States visible to user: `not-linked` / `linked` / `needs-refresh`
- Only workspace owners can edit; viewers see read-only state indicator

### Node inspector

- New "GitHub repo" field in the C4Node inspector (Container & System types only)
- Validate-on-blur: hits `repo_get_metadata` (via a thin backend endpoint) and shows ✓ / ✗
- Optional `repo_branch` advanced input (defaults to repo's default branch when null)
- Disabled if workspace has no token, with a helpful tooltip

## 7. Out of scope (deliberate)

- Local cloning / ripgrep / AST-based analysis — Phase 3 explicitly skipped
- Drift detection ("sync diagram with code")
- Per-user GitHub tokens (workspace-only)
- Per-repo token override (no cross-org repos in MVP)
- GitHub Enterprise (only github.com)
- GitLab / Bitbucket / other providers

## 8. Phasing

### D1 — Plumbing (no AI yet)

Deliverables:
1. Migration: `workspaces.github_token_encrypted`, `objects.repo_url`, `objects.repo_branch`
2. Service-layer encryption + getters/setters for workspace token (reuse existing API-key crypto helpers)
3. `RepoCredentialsService` — token resolution + a thin GitHub HTTP client with retry/backoff
4. Object service validates `repo_url` only on Container/System types
5. New backend endpoints:
   - `POST /workspaces/{id}/github-token` (set + validate)
   - `DELETE /workspaces/{id}/github-token` (clear)
   - `POST /workspaces/{id}/github-token/test` (validate without saving)
   - `POST /repos/lookup` (calls `GET /repos/{owner}/{name}`, returns metadata for inspector validate-on-blur)
6. Frontend: workspace settings GitHub block (PAT input, test, clear)
7. Frontend: C4Node inspector new "GitHub repo" field with validate-on-blur

Acceptance:
- I can save a token in workspace settings; "Test connection" succeeds
- I can paste `https://github.com/microsoft/typescript` into a Container's repo field; it validates ✓
- After full page reload, the link is still there
- Clearing the token removes it

### D2 — Worker node + tools

Deliverables:
1. All 9 tools implemented (HTTP client, per-turn LRU cache, rate-limit middleware)
2. `repo_researcher` LangGraph node with parameterized system prompt
3. `collect_repo_manifest(active_diagram_id, db)` — non-recursive yet (active scope only)
4. Supervisor system-prompt extension with dynamic `delegate` enum
5. Wire `repo_researcher` into the LangGraph topology
6. Tool-call SSE plumbing already exists (no changes needed)

Acceptance:
- Linked repo + "Опиши мій auth-service" → supervisor delegates to `repo:auth-service` → text response grounded in repo
- Token invalid → graceful chat warning, no crash
- Asking about a repo with no token → supervisor doesn't see the target
- Rate-limit retry observable in logs

### D3 — Multi-repo + visualize-this

Deliverables:
1. `collect_repo_manifest` walks descendant diagrams recursively (with cycle guard)
2. Multi-repo manifest (multiple `repo:*` targets)
3. Supervisor prompt cookbook: example dialogues showing `repo_researcher` → `planner` → `diagram-agent` flow for "visualize this Container"
4. Integration test: System with 2 child Containers, each with a repo, presents 2 separate `repo:*` targets
5. End-to-end test: "візуалізуй цей Container" produces a Component diagram

Acceptance:
- A System with 2 child Containers (each linked to a repo) presents as 2 `repo:*` targets to the supervisor
- "Візуалізуй цей Container" runs the full chain and produces a Component-level child diagram populated with code-derived nodes

## 9. Risks & open questions

| Risk | Mitigation |
|---|---|
| GitHub Search API is slow/limited (single-branch, no regex, indexing lag) | Document limitation; `repo_search_code` returns best-effort. If it becomes blocking, revisit Phase 3 (clone+ripgrep) |
| Large monorepo blows context on `repo_list_tree` | Default depth=2; LLM must explicitly request deeper. Add total-files cap (e.g. 500) with truncation hint |
| Token leaks in logs | Never log raw tokens; redact at logger level. Mask in error messages |
| Diagram-tree cycles | Reuse existing 3-level cap from `useDiagramBreadcrumbs` |
| Slug collisions when 2 nodes share a name | Append short-uuid suffix; surface in the manifest description |
