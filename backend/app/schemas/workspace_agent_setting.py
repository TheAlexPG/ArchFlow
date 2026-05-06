import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class WorkspaceAgentSettingBase(BaseModel):
    """Fields shared by create and read schemas."""

    key: str = Field(..., min_length=1, max_length=128)
    agent_id: str | None = Field(
        None,
        max_length=64,
        description="Agent this setting applies to. NULL means global workspace default.",
    )
    is_secret: bool = False


class WorkspaceAgentSettingCreate(WorkspaceAgentSettingBase):
    """Payload for creating or upserting a workspace agent setting.

    Exactly one of ``value_plain`` or ``value_secret`` should be provided.
    ``value_encrypted`` is never accepted from callers — encryption happens
    server-side in ``agent_settings_service``.
    """

    value_plain: Any | None = Field(
        None,
        description="Non-secret value stored as plain JSONB.",
    )
    value_secret: str | None = Field(
        None,
        description=(
            "Secret value as plaintext at the API boundary. "
            "The server encrypts this before persisting; never returned in reads."
        ),
    )

    @model_validator(mode="after")
    def _check_value_consistency(self) -> "WorkspaceAgentSettingCreate":
        if self.value_plain is not None and self.value_secret is not None:
            raise ValueError(
                "Provide either value_plain or value_secret, not both."
            )
        if self.is_secret and self.value_plain is not None:
            raise ValueError(
                "Use value_secret for secret settings, not value_plain."
            )
        return self


class WorkspaceAgentSettingRead(WorkspaceAgentSettingBase):
    """Read-side representation returned by the API.

    Raw secret values are never exposed. Callers use ``has_value`` to determine
    whether a value exists without seeing the underlying data.
    """

    id: uuid.UUID
    workspace_id: uuid.UUID
    has_value: bool = Field(
        description=(
            "True when either value_plain or value_encrypted is set. "
            "Secret values are never returned directly."
        )
    )
    created_at: datetime
    updated_at: datetime
    updated_by: uuid.UUID | None = None

    model_config = {"from_attributes": True}
