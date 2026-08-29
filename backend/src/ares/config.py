from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARES_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    fake_crm_webhook_secret: str = "local-dev-only-change-me"
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)

    @model_validator(mode="after")
    def reject_development_secret_outside_development(self) -> "Settings":
        if (
            self.environment != "development"
            and self.fake_crm_webhook_secret == "local-dev-only-change-me"
        ):
            raise ValueError("ARES_FAKE_CRM_WEBHOOK_SECRET must be configured")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
