# Authentication

ArchFlow accepts two credential types on the same `Authorization` header:

- **JWT bearer** — short-lived access token from `POST /auth/login` (or refresh).
- **API key** — long-lived token prefixed with `ak_`, ideal for agents. See [API Keys](./api-keys.md).

```
Authorization: Bearer <jwt access token>
Authorization: Bearer ak_<api key secret>
```

## POST /api/v1/auth/register
Public. Create a new user. Returns access + refresh JWTs and provisions a personal workspace.

**Request**
```json
{ "email": "agent@example.com", "name": "Agent Smith", "password": "min-6-chars" }
```

**201 response**
```json
{ "access_token": "eyJ...", "refresh_token": "eyJ...", "token_type": "bearer" }
```

## POST /api/v1/auth/login
Public. Exchange email + password for access + refresh JWTs.

```json
{ "email": "agent@example.com", "password": "..." }
```

## POST /api/v1/auth/refresh
Trade a refresh token for a fresh access + refresh pair.

```
POST /api/v1/auth/refresh?refresh_token=eyJ...
```

## GET /api/v1/auth/me
JWT or API key. Returns the authenticated user.

```json
{ "id": "uuid", "email": "agent@example.com", "name": "Agent Smith", "created_at": "..." }
```
