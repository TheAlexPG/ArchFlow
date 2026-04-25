# API Docs at /docs — Design

**Status:** approved 2026-04-25
**Owner:** main branch
**Goal:** Give AI agents (and humans driving them) a single, curated reference for ArchFlow's HTTP and WebSocket API.

## Why

ArchFlow exposes a sizeable REST surface plus a workspace-scoped WebSocket. Today there is no single agent-facing entry point — agents must read source files to discover endpoints, auth headers, and payload shapes. A curated `/docs` page (mirrored as markdown in the repo) closes that gap and makes the project agent-friendly out of the box.

## Scope

In scope:
- Public route `/docs` on the frontend, no auth gate (agents need to read it without a session).
- Curated coverage of: auth, api-keys, workspaces, objects, connections, diagrams, technologies, webhooks, realtime WebSocket.
- Lighter-touch coverage of: drafts, comments, activity, members, teams, versions, invites, my-invites, notifications (one-line summary per endpoint, no full schema dump).
- Markdown mirror under `docs/api/` matching the page sections.

Out of scope:
- Live "try it" panels.
- Auto-generated OpenAPI rendering.
- Schema validation tooling.
- Sidebar navigation in the authenticated app shell — the page stands alone like `/privacy` and `/terms`.

## Architecture

### Routing
- Single route `/docs` registered in `App.tsx` next to the public `/terms` and `/privacy` routes (no `<ProtectedRoute>` wrap).
- One page, in-page anchor sections (`#auth`, `#objects`, etc.) — no sub-routes.

### Layout
- New `pages/DocsPage.tsx` reuses the visual chrome of `LegalLayout` (dark `#0a0a0f`, orange ambient glow, IBM Plex) but with:
  - Wider container (`max-w-6xl`) for endpoint tables.
  - Sticky left-side ToC on `lg:` breakpoints (`<aside>`), inline ToC on small screens.
  - Reusable `<Endpoint>` and `<Schema>` presentation components defined inside `pages/docs/`.
- Section components live under `frontend/src/pages/docs/` so the page file stays readable:
  - `IntroSection.tsx`
  - `AuthSection.tsx`
  - `ApiKeysSection.tsx`
  - `WorkspacesSection.tsx`
  - `ObjectsSection.tsx`
  - `ConnectionsSection.tsx`
  - `DiagramsSection.tsx`
  - `TechnologiesSection.tsx`
  - `WebhooksSection.tsx`
  - `RealtimeSection.tsx`
  - `MiscSection.tsx` (drafts, comments, activity, members, teams, versions, invites, notifications — short summaries)

### Markdown mirror
- `docs/api/` directory:
  - `index.md` — overview, base URL, auth options, conventions
  - `auth.md`, `api-keys.md`, `workspaces.md`, `objects.md`, `connections.md`, `diagrams.md`, `technologies.md`, `webhooks.md`, `realtime.md`, `misc.md`
- Same headings/anchors as the web page so cross-linking is trivial.

### Content sourcing
- Hand-written, derived from reading each `backend/app/api/v1/*.py` and matching schemas in `backend/app/schemas/`.
- Each endpoint entry includes: method, path, auth requirement (JWT / API key / either), summary, key request fields, key response fields, one example.

## Data flow

The page is fully static — no API calls, no React Query usage. All content is hard-coded in TSX. This keeps the route deployable without a backend.

## Error handling

Static page; no runtime errors expected beyond the React render path. The `/docs` route is rendered for everyone, signed in or not.

## Testing

- Frontend: `npm run build` must succeed (type-check + Vite build). No new unit tests required for a static content page.
- Backend: `python -m pytest` must stay green (no backend changes are part of this work, but the user asked us to verify the suite passes before opening a PR).

## Delivery

1. Create branch `docs/api-reference`.
2. Implement frontend page + markdown mirror.
3. Run frontend build and backend tests.
4. Commit, push, open PR to `main` via `gh`.
