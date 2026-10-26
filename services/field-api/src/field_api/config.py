"""SCMTIPS Field API Configuration (Task T1.011 / FR1.009)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    FIELD_ENV: str = "development"
    FIELD_PORT: int = 8000
    FIELD_DATABASE_URL: str = "postgresql://field_app:devpassword@localhost:5450/field"
    FIELD_CORE_JWKS_URL: str = "http://localhost:8001/.well-known/jwks.json"
    FIELD_ERP_SIM_URL: str = "http://localhost:8002"
    FIELD_JWKS_MAX_STALE_S: int = 3600
    FIELD_IDEMPOTENCY_TTL_S: int = 86400  # 24 hours
    FIELD_CURSOR_HMAC_SECRET: str = "dev-cursor-hmac-secret-change-in-production-min32bytes"
    FIELD_DEFAULT_PAGE_SIZE: int = 50
    FIELD_MAX_PAGE_SIZE: int = 200
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
