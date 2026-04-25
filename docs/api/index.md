# ArchFlow API Reference

Curated reference for AI agents and integrators of the ArchFlow API.

The web version of these docs lives at `/docs` on any ArchFlow deployment.

## Base URL & versioning
All HTTP routes are mounted under `/api/v1`. Breaking changes will introduce `/api/v2`.

Example: `https://api.archflow.tools/api/v1`

## Conventions
- Identifiers are UUID v4 unless noted.
- Timestamps are ISO 8601 UTC strings.
- Bodies and responses use `application/json`.
- Errors are `{"detail": "<message>"}` with HTTP status codes (400/401/403/404/409/429/5xx).
- Workspace-scoped endpoints honor the `X-Workspace-ID` header. If omitted, the user's default workspace is used.

## Health
`GET /health` → `200 {"status": "ok"}`

## Sections
- [Authentication](./auth.md)
- [API Keys](./api-keys.md)
- [Workspaces](./workspaces.md)
- [Objects](./objects.md)
- [Connections](./connections.md)
- [Diagrams](./diagrams.md)
- [Technologies](./technologies.md)
- [Webhooks](./webhooks.md)
- [Realtime (WebSocket)](./realtime.md)
- [Other endpoints](./misc.md)
