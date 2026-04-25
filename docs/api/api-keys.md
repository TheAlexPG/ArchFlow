# API Keys

API keys are long-lived bearer credentials suited for AI agents and CI integrations. They begin with `ak_` and travel on the `Authorization` header. The full secret is returned **only at creation time**.

## POST /api/v1/api-keys
JWT. Create a key.

```json
{ "name": "agent-smith-prod", "permissions": ["read", "write"], "expires_in_days": 365 }
```

**201 response (secret returned once)**
```json
{
  "id": "uuid",
  "name": "agent-smith-prod",
  "key_prefix": "ak_aB3d",
  "permissions": ["read", "write"],
  "expires_at": "2027-04-25T...",
  "last_used_at": null,
  "revoked_at": null,
  "created_at": "...",
  "secret": "ak_aB3d_<remainder>"
}
```

## GET /api/v1/api-keys
JWT. List all keys you own. Secret is never returned.

## DELETE /api/v1/api-keys/{key_id}
JWT. Revoke a key. 204 / 404.

## Using a key
```bash
curl https://api.archflow.tools/api/v1/auth/me \
  -H "Authorization: Bearer ak_aB3d_<rest>"
```

Mutating endpoints called via API key are rate-limited per user; exceeding the limit returns `429 Too Many Requests`.
