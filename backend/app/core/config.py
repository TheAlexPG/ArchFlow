from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

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
    anthropic_api_key: str | None = None
    # Default to the latest Claude model the user selects in their .env.
    anthropic_model: str = "claude-sonnet-4-5-20250929"

    # Google OAuth (opt-in — leave client_id/secret blank to disable the button)
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/oauth/google/callback"
    frontend_url: str = "http://localhost:5173"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",")]


settings = Settings()
