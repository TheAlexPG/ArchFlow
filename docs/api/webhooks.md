# Webhooks

HTTPS callbacks for workspace events. Each delivery is HMAC-signed with the per-webhook secret. Secret is shown only at creation.

## Event catalog

`GET /api/v1/webhooks/events` (public)

```json
[
  "object.created", "object.updated", "object.deleted",
  "connection.created", "connection.updated", "connection.deleted",
  "diagram.created", "diagram.updated", "diagram.deleted",
  "draft.applied"
]
```

## POST /api/v1/webhooks
JWT.

```json
{ "url": "https://hooks.example.com/archflow", "events": ["object.created", "connection.created"] }
```

**201**
```json
{
  "id": "uuid",
  "url": "https://hooks.example.com/archflow",
  "events": ["object.created", "connection.created"],
  "enabled": true,
  "failure_count": 0,
  "last_delivery_at": null,
  "last_status": null,
  "created_at": "...",
  "secret": "whsec_<hex>"
}
```

## GET /api/v1/webhooks
JWT. List your webhooks (no secrets).

## DELETE /api/v1/webhooks/{webhook_id}
JWT. Delete.

## POST /api/v1/webhooks/{webhook_id}/test
JWT. Queue a synthetic ping.

## Delivery payload
Each delivery is `POST application/json`:
```json
{ "event": "<name>", "data": { "...event-specific body..." } }
```
HMAC-SHA256 of the body with the secret is sent as a request header for verification.
