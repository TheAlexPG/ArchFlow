"""Workspace agent settings (LLM provider/key, context, analytics, policies, overrides)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.permissions_dep import require_role
from app.api.workspace_dep import get_current_workspace
from app.core.database import get_db
from app.models.activity_log import ActivityAction, ActivityLog, ActivityTargetType
from app.models.user import User
from app.models.workspace import Role, Workspace
from app.services import agent_settings_service

router = APIRouter(prefix="/agents/settings", tags=["agents"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class LLMSettingsRead(BaseModel):
    provider: str | None
    base_url: str | None
    model_default: str | None
    # Manual context-window override (tokens). Null = let LiteLLM auto-detect.
    context_window: int | None = None
    has_key: bool  # NEVER expose raw key


class ContextSettingsRead(BaseModel):
    threshold: float
    strategy: str
    tool_result_trim_threshold_tokens: int


class PerAgentSettingsRead(BaseModel):
    model: str | None = None
    turn_limit: int | None = None
    budget_usd: str | None = None
    budget_scope: str | None = None
    context_threshold: float | None = None


class ModelPricingRead(BaseModel):
    input_per_million: str
    output_per_million: str


class AgentSettingsResponse(BaseModel):
    litellm: LLMSettingsRead
    context: ContextSettingsRead
    analytics_consent: str
    agent_edits_policy: str
    agents: dict[str, PerAgentSettingsRead]
    model_pricing: dict[str, ModelPricingRead]


# ---------------------------------------------------------------------------
# Update models
# ---------------------------------------------------------------------------


class LLMSettingsUpdate(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    model_default: str | None = None
    context_window: int | None = None
    # Plaintext at API boundary, encrypted server-side; pass null to clear.
    api_key: str | None = None


class AgentSettingsUpdate(BaseModel):
    """All fields optional — only provided keys are updated. Use null to clear."""

    litellm: LLMSettingsUpdate | None = None
    context: dict | None = None
    analytics_consent: str | None = None
    agent_edits_policy: str | None = None
    agents: dict[str, PerAgentSettingsRead] | None = None
    model_pricing: dict[str, ModelPricingRead] | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_value(row: Any) -> Any:
    """Extract the plain value from a WorkspaceAgentSetting row."""
    raw = row.value_plain
    if isinstance(raw, dict):
        return raw.get("value", raw)
    return raw


async def _build_response(
    db: AsyncSession,
    workspace_id: UUID,
) -> AgentSettingsResponse:
    """Build AgentSettingsResponse from stored settings merged with spec defaults.

    Uses list_settings (simple SELECT, no UNION ALL) then applies defaults from
    ResolvedAgentSettings field defaults to avoid the UNION ALL + scalars() issue
    with asyncpg.
    """
    from app.services.agent_settings_service import ResolvedAgentSettings

    # Fetch all rows for this workspace at once.
    all_rows = await agent_settings_service.list_settings(db, workspace_id)

    # Separate global (agent_id=None) from per-agent rows.
    global_rows: dict[str, Any] = {
        r.key: r for r in all_rows if r.agent_id is None
    }

    # Spec defaults (from ResolvedAgentSettings dataclass defaults).
    _defaults = ResolvedAgentSettings(workspace_id=workspace_id, agent_id="general")

    def _get(key: str, default: Any) -> Any:
        row = global_rows.get(key)
        if row is None:
            return default
        return _row_value(row)

    # LLM settings
    provider = _get("litellm_provider", _defaults.litellm_provider)
    base_url = _get("litellm_base_url", _defaults.litellm_base_url)
    model_default = _get("litellm_model_default", _defaults.litellm_model)
    context_window_raw = _get("litellm_context_window", _defaults.litellm_context_window)
    context_window = int(context_window_raw) if context_window_raw is not None else None

    # has_key: check for a secret row
    api_key_row = global_rows.get("litellm_api_key")
    has_key = (
        api_key_row is not None
        and api_key_row.is_secret
        and api_key_row.value_encrypted is not None
    )

    # Context settings
    context_threshold = float(_get("context_threshold", _defaults.context_threshold))
    context_strategy = _get("context_strategy", _defaults.context_strategy)
    tool_trim = int(
        _get(
            "tool_result_trim_threshold_tokens",
            _defaults.tool_result_trim_threshold_tokens,
        )
    )

    # Top-level scalars
    analytics_consent = _get("analytics_consent", _defaults.analytics_consent)
    agent_edits_policy = _get("agent_edits_policy", _defaults.agent_edits_policy)

    # Model pricing overrides
    model_pricing: dict[str, ModelPricingRead] = {}
    for row in all_rows:
        if row.agent_id is None and row.key.startswith("model_pricing."):
            model_id = row.key[len("model_pricing."):]
            val = _row_value(row)
            if isinstance(val, dict):
                model_pricing[model_id] = ModelPricingRead(
                    input_per_million=str(val.get("input_per_million", "0")),
                    output_per_million=str(val.get("output_per_million", "0")),
                )

    # Per-agent overrides
    agents_out: dict[str, PerAgentSettingsRead] = {}
    for row in all_rows:
        if row.agent_id is not None:
            aid = row.agent_id
            if aid not in agents_out:
                agents_out[aid] = PerAgentSettingsRead()
            val = _row_value(row)
            if row.key == "model":
                agents_out[aid] = agents_out[aid].model_copy(
                    update={"model": str(val) if val is not None else None}
                )
            elif row.key == "turn_limit":
                agents_out[aid] = agents_out[aid].model_copy(
                    update={"turn_limit": int(val) if val is not None else None}
                )
            elif row.key == "budget_usd":
                agents_out[aid] = agents_out[aid].model_copy(
                    update={"budget_usd": str(val) if val is not None else None}
                )
            elif row.key == "budget_scope":
                agents_out[aid] = agents_out[aid].model_copy(
                    update={"budget_scope": str(val) if val is not None else None}
                )
            elif row.key == "context_threshold":
                agents_out[aid] = agents_out[aid].model_copy(
                    update={
                        "context_threshold": float(val) if val is not None else None
                    }
                )

    return AgentSettingsResponse(
        litellm=LLMSettingsRead(
            provider=provider,
            base_url=base_url,
            model_default=model_default,
            context_window=context_window,
            has_key=has_key,
        ),
        context=ContextSettingsRead(
            threshold=context_threshold,
            strategy=context_strategy,
            tool_result_trim_threshold_tokens=tool_trim,
        ),
        analytics_consent=analytics_consent,
        agent_edits_policy=agent_edits_policy,
        agents=agents_out,
        model_pricing=model_pricing,
    )


async def _write_audit_log(
    db: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    updated_keys: list[str],
    api_key_action: str | None,
) -> None:
    """Write workspace.agent_settings_updated audit log entry."""
    changes: dict[str, Any] = {
        "event": "workspace.agent_settings_updated",
        "updated_keys": updated_keys,
    }
    if api_key_action is not None:
        changes["litellm.api_key"] = api_key_action

    entry = ActivityLog(
        target_type=ActivityTargetType.WORKSPACE,
        target_id=workspace_id,
        action=ActivityAction.UPDATED,
        changes=changes,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    db.add(entry)
    await db.flush()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=AgentSettingsResponse)
async def get_agent_settings(
    workspace: Workspace = Depends(get_current_workspace),
    _role: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> AgentSettingsResponse:
    """Read merged settings for current user's workspace. Workspace owner/admin only.

    Returns has_key boolean instead of raw secret.
    """
    return await _build_response(db, workspace.id)


@router.put("", response_model=AgentSettingsResponse)
async def update_agent_settings(
    body: AgentSettingsUpdate,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    _role: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> AgentSettingsResponse:
    """Deep merge provided fields. api_key plaintext encrypted before write.

    Audit logged with diff (no raw secret values in audit).
    """
    workspace_id = workspace.id
    user_id = current_user.id
    updated_keys: list[str] = []
    api_key_action: str | None = None

    # --- litellm ---
    if body.litellm is not None:
        llm = body.litellm
        if llm.provider is not None:
            await agent_settings_service.set_setting(
                db, workspace_id, None, "litellm_provider",
                value_plain=llm.provider, updated_by=user_id,
            )
            updated_keys.append("litellm.provider")
        if llm.base_url is not None:
            await agent_settings_service.set_setting(
                db, workspace_id, None, "litellm_base_url",
                value_plain=llm.base_url, updated_by=user_id,
            )
            updated_keys.append("litellm.base_url")
        if llm.model_default is not None:
            await agent_settings_service.set_setting(
                db, workspace_id, None, "litellm_model_default",
                value_plain=llm.model_default, updated_by=user_id,
            )
            updated_keys.append("litellm.model_default")
        if "context_window" in body.litellm.model_fields_set:
            await agent_settings_service.set_setting(
                db, workspace_id, None, "litellm_context_window",
                value_plain=llm.context_window, updated_by=user_id,
            )
            updated_keys.append("litellm.context_window")
        # api_key field was explicitly included in the payload (even if null).
        # We check model_fields_set to distinguish "not provided" from "null".
        if "api_key" in body.litellm.model_fields_set:
            if llm.api_key is not None:
                # Encrypt and store.
                await agent_settings_service.set_setting(
                    db, workspace_id, None, "litellm_api_key",
                    value_secret=llm.api_key, updated_by=user_id,
                )
                api_key_action = "litellm.api_key set"
            else:
                # Clear the key row.
                await agent_settings_service.set_setting(
                    db, workspace_id, None, "litellm_api_key",
                    value_plain=None, value_secret=None, updated_by=user_id,
                )
                api_key_action = "litellm.api_key cleared"

    # --- context ---
    if body.context is not None:
        ctx = body.context
        if "threshold" in ctx:
            await agent_settings_service.set_setting(
                db, workspace_id, None, "context_threshold",
                value_plain=ctx["threshold"], updated_by=user_id,
            )
            updated_keys.append("context.threshold")
        if "strategy" in ctx:
            await agent_settings_service.set_setting(
                db, workspace_id, None, "context_strategy",
                value_plain=ctx["strategy"], updated_by=user_id,
            )
            updated_keys.append("context.strategy")
        if "tool_result_trim_threshold_tokens" in ctx:
            await agent_settings_service.set_setting(
                db, workspace_id, None, "tool_result_trim_threshold_tokens",
                value_plain=ctx["tool_result_trim_threshold_tokens"], updated_by=user_id,
            )
            updated_keys.append("context.tool_result_trim_threshold_tokens")

    # --- top-level scalar settings ---
    if body.analytics_consent is not None:
        await agent_settings_service.set_setting(
            db, workspace_id, None, "analytics_consent",
            value_plain=body.analytics_consent, updated_by=user_id,
        )
        updated_keys.append("analytics_consent")

    if body.agent_edits_policy is not None:
        await agent_settings_service.set_setting(
            db, workspace_id, None, "agent_edits_policy",
            value_plain=body.agent_edits_policy, updated_by=user_id,
        )
        updated_keys.append("agent_edits_policy")

    # --- per-agent overrides ---
    if body.agents is not None:
        for agent_id, overrides in body.agents.items():
            override_data = overrides.model_dump(exclude_none=True)
            for field_name, val in override_data.items():
                db_key = field_name  # "model", "turn_limit", "budget_usd", etc.
                if field_name == "budget_usd" and val is not None:
                    val = str(val)
                await agent_settings_service.set_setting(
                    db, workspace_id, agent_id, db_key,
                    value_plain=val, updated_by=user_id,
                )
                updated_keys.append(f"agents.{agent_id}.{field_name}")

    # --- model_pricing ---
    if body.model_pricing is not None:
        for model_id, pricing in body.model_pricing.items():
            await agent_settings_service.set_setting(
                db, workspace_id, None, f"model_pricing.{model_id}",
                value_plain={
                    "input_per_million": pricing.input_per_million,
                    "output_per_million": pricing.output_per_million,
                },
                updated_by=user_id,
            )
            updated_keys.append(f"model_pricing.{model_id}")

    # Audit log — no raw secrets.
    if updated_keys or api_key_action is not None:
        await _write_audit_log(db, workspace_id, user_id, updated_keys, api_key_action)

    await db.commit()
    return await _build_response(db, workspace_id)
