from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ares.ai.models import DEFAULT_MODEL


class CRMConnectionSettings(BaseModel):
    connection_id: UUID
    base_url: str
    api_key_env: str
    webhook_secret_env: str | None = None

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("invalid_crm_base_url")
        return value.rstrip("/")

    @field_validator("api_key_env", "webhook_secret_env")
    @classmethod
    def server_secret_reference(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.startswith("ARES_CRM_SECRET_")
            or not all(c.isupper() or c.isdigit() or c == "_" for c in value)
        ):
            raise ValueError("invalid_crm_secret_reference")
        return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARES_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    crm_connections: dict[UUID, CRMConnectionSettings] = {}
    worker_poll_seconds: float = 5.0
    worker_stale_seconds: int = 180
    require_worker: bool = False
    background_execution: bool = True
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
    rate_limit_requests_per_minute: int = 120
    rate_limit_writes_per_minute: int = 20
    rate_limit_chat_per_minute: int = 6
    rate_limit_ip_per_minute: int = 600

    @model_validator(mode="after")
    def reject_development_secret_outside_development(self) -> "Settings":
        if (
            min(
                self.rate_limit_requests_per_minute,
                self.rate_limit_writes_per_minute,
                self.rate_limit_chat_per_minute,
                self.rate_limit_ip_per_minute,
            )
            < 1
        ):
            raise ValueError("Request rate limits must be positive")
        if self.worker_poll_seconds < 1 or self.worker_stale_seconds < 30:
            raise ValueError("invalid_worker_interval")
        if self.environment not in {"development", "demonstration", "staging", "production"}:
            raise ValueError("invalid_environment")
        if self.environment != "development" and self.event_journal_backend != "postgres":
            raise ValueError("PostgreSQL is required outside development")
        if self.environment == "demonstration" and not self.crm_connections:
            raise ValueError("Demonstration requires explicit per-company CRM connections")
        if len({config.connection_id for config in self.crm_connections.values()}) != len(
            self.crm_connections
        ):
            raise ValueError("CRM connection identifiers must be unique across companies")
        if self.environment != "development":
            import os

            credentials = [
                self.tick_secret.get_secret_value(),
                self.fake_crm_webhook_secret,
                self.supabase_secret_key.get_secret_value(),
                *[
                    os.environ.get(config.api_key_env, "")
                    for config in self.crm_connections.values()
                ],
                *[
                    os.environ.get(config.webhook_secret_env or "", "")
                    for config in self.crm_connections.values()
                ],
            ]
            if any(len(value) < 24 or value.startswith("REPLACE_") for value in credentials):
                raise ValueError("Strong server-only credentials are required outside development")
            if not self.require_worker or self.background_execution:
                raise ValueError("A supervised independent worker is required outside development")
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
