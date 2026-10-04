from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ares.ai.models import DEFAULT_MODEL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARES_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    fake_crm_webhook_secret: str = "local-dev-only-change-me"
    crm_provider: Literal["embedded_fake", "http_fake"] = "embedded_fake"
    fake_crm_base_url: str = "http://127.0.0.1:8010"
    fake_crm_api_key: SecretStr = SecretStr("local-sandbox-key")
    fake_crm_timeout_seconds: float = 2.0
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    event_journal_backend: Literal["postgres", "memory"] = "postgres"
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:55422/postgres"
    tenant_id: UUID = UUID("20000000-0000-0000-0000-000000000001")
    supabase_url: str = "http://127.0.0.1:55421"
    supabase_publishable_key: str = ""
    supabase_secret_key: SecretStr = SecretStr("")
    tick_secret: SecretStr = SecretStr("local-dev-tick-secret")
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = DEFAULT_MODEL
    recommendation_estimated_cost_usd: float = 0.01

    @model_validator(mode="after")
    def reject_development_secret_outside_development(self) -> "Settings":
        if (
            self.environment != "development"
            and self.fake_crm_webhook_secret == "local-dev-only-change-me"
        ):
            raise ValueError("ARES_FAKE_CRM_WEBHOOK_SECRET must be configured")
        if self.environment != "development" and not self.supabase_publishable_key:
            raise ValueError("ARES_SUPABASE_PUBLISHABLE_KEY must be configured")
        if self.environment != "development" and not self.supabase_secret_key.get_secret_value():
            raise ValueError("ARES_SUPABASE_SECRET_KEY must be configured")
        if (
            self.environment != "development"
            and self.tick_secret.get_secret_value() == "local-dev-tick-secret"
        ):
            raise ValueError("ARES_TICK_SECRET must be configured")
        if self.fake_crm_timeout_seconds <= 0:
            raise ValueError("ARES_FAKE_CRM_TIMEOUT_SECONDS must be greater than zero")
        if (
            self.environment != "development"
            and self.crm_provider == "http_fake"
            and self.fake_crm_api_key.get_secret_value() == "local-sandbox-key"
        ):
            raise ValueError("ARES_FAKE_CRM_API_KEY must be configured")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
