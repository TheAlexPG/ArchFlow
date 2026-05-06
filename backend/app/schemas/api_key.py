from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Allowed scope / permission tokens for API keys.
#
# Legacy coarse tokens ("read", "write", "admin") are preserved for backward
# compatibility with keys created before the agents-scope epic.
#
# New agent-specific tokens map to the scope hierarchy:
#   agents:read < agents:invoke < agents:write < agents:admin
#
# Wildcard "*" grants all permissions; reserved for internal / service use.
# ---------------------------------------------------------------------------

ALLOWED_SCOPES: frozenset[str] = frozenset(
    {
        # Wildcard — satisfies any scope check.
        "*",
        # Legacy coarse tokens (preserved for backward compat).
        "read",
        "write",
        "admin",
        # Agent-specific scope hierarchy (§2.10).
        "agents:read",
        "agents:invoke",
        "agents:write",
        "agents:admin",
    }
)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    permissions: list[str] = Field(default_factory=lambda: ["read"])
    # Optional lifetime in days. None = never expires.
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("permissions")
    @classmethod
    def _validate_permissions(cls, v: list[str]) -> list[str]:
        invalid = [s for s in v if s not in ALLOWED_SCOPES]
        if invalid:
            raise ValueError(f"unknown scopes: {invalid}")
        return v


class ApiKeyResponse(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    permissions: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyWithSecret(ApiKeyResponse):
    """Returned exactly once at creation — secret is not persisted in plaintext."""

    secret: str
