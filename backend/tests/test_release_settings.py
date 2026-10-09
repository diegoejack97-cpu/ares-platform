from uuid import uuid4

import pytest
from pydantic import ValidationError

from ares.config import CRMConnectionSettings, Settings


def demo(monkeypatch, **overrides):
    monkeypatch.setenv("ARES_CRM_SECRET_RELEASE_API", "a" * 32)
    monkeypatch.setenv("ARES_CRM_SECRET_RELEASE_WEBHOOK", "b" * 32)
    defaults = dict(
        _env_file=None,
        environment="demonstration",
        event_journal_backend="postgres",
        supabase_publishable_key="synthetic-public-key",
        supabase_secret_key="c" * 32,
        tick_secret="d" * 32,
        fake_crm_webhook_secret="e" * 32,
        require_worker=True,
        background_execution=False,
        crm_connections={
            uuid4(): CRMConnectionSettings(
                connection_id=uuid4(),
                base_url="http://crm:8010",
                api_key_env="ARES_CRM_SECRET_RELEASE_API",
                webhook_secret_env="ARES_CRM_SECRET_RELEASE_WEBHOOK",
            )
        },
    )
    return Settings(**{**defaults, **overrides})


def test_demo_requires_explicit_connections_and_supervised_worker(monkeypatch):
    assert demo(monkeypatch).environment == "demonstration"
    for overrides in (
        {"crm_connections": {}},
        {"event_journal_backend": "memory"},
        {"require_worker": False},
        {"background_execution": True},
        {"tick_secret": "REPLACE_WITH_RANDOM_SECRET"},
    ):
        with pytest.raises(ValidationError):
            demo(monkeypatch, **overrides)


def test_connection_config_rejects_credentials_in_urls_and_public_secret_references():
    for url, reference in [
        ("https://secret:password@crm.invalid", "ARES_CRM_SECRET_API"),
        ("https://crm.invalid?token=secret", "ARES_CRM_SECRET_API"),
        ("http://crm:8010", "VITE_API_KEY"),
    ]:
        with pytest.raises(ValidationError):
            CRMConnectionSettings(connection_id=uuid4(), base_url=url, api_key_env=reference)
