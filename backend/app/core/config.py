from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Database
    database_url: str = "postgresql+asyncpg://archflow:archflow@localhost:5432/archflow"
    database_url_sync: str = "postgresql://archflow:archflow@localhost:5432/archflow"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # CORS
    backend_cors_origins: str = "http://localhost:5173"

    # AI features (opt-in)
    # NOTE: anthropic_api_key is now legacy/unused after the ai_service migration
    # to the diagram-explainer agent (task agent-core-mvp-062).  The field is
    # kept here for back-compat so existing deployments don't break on startup.
    # TODO: remove in Phase 2 once frontend uses /api/v1/agents/diagram-explainer/invoke directly.
    anthropic_api_key: str | None = None
    # Default to the latest Claude model the user selects in their .env.
    anthropic_model: str = "claude-sonnet-4-5-20250929"

    # Google OAuth (opt-in — leave client_id/secret blank to disable the button)
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/oauth/google/callback"
    frontend_url: str = "http://localhost:5173"

    # Agent platform — Fernet key for encrypting workspace LLM provider keys + Langfuse keys.
    # Must be a 32-byte url-safe base64-encoded string (44 chars).
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # noqa: E501
    agents_secret_key: SecretStr | None = None

    # Langfuse — admin-instance opt-in tracing for agent calls.
    # When all three are set, app/agents/tracing.py registers litellm callbacks
    # at startup. Per-call routing is gated by workspace analytics_consent
    # (off / errors_only / full) via metadata in app/agents/llm.py.
    # Conventional unprefixed env names (LANGFUSE_*) match the LiteLLM SDK
    # convention and the langfuse/skills setup pattern.
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str | None = None

    # Agent invocation rate limits — operator-level, not per-workspace.
    # Defaults are 10× the original spec defaults (which were 600/h, 6000/d,
    # 1000/d, 10000/d). Tune via env vars in production.
    agent_rate_limit_api_key_per_hour: int = 6000
    agent_rate_limit_api_key_per_day: int = 60000
    agent_rate_limit_user_per_day: int = 10000
    agent_rate_limit_workspace_per_day: int = 100000

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",")]


settings = Settings()
