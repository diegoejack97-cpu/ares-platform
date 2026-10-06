"""Resolve server-owned credentials and a CRM connection inside the active tenant.

The environment manifest contains references, never client-supplied secrets.
The legacy local sandbox fallback is restricted to the development tenant.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from ares.config import Settings
from ares.connectors.http_fake_crm import CRMProviderRequestError, FakeCRMHTTPProvider
from ares.connectors.models import CRMCapabilities, CRMDealPage, CRMWriteResult


def webhook_for(settings: Settings, connection_id: UUID) -> tuple[UUID, str]:
    """A webhook URL selects a server-owned connection; its signature still authenticates it."""
    tenant_config = next(
        (
            (tenant, config)
            for tenant, config in settings.crm_connections.items()
            if config.connection_id == connection_id
        ),
        None,
    )
    if tenant_config:
        tenant, config = tenant_config
        secret = os.environ.get(config.webhook_secret_env or "", "")
    elif settings.environment == "development":
        tenant, secret = settings.tenant_id, settings.fake_crm_webhook_secret
    else:
        raise CRMProviderRequestError(
            "Unknown webhook connection", status_code=404, code="connection_unavailable"
        )
    with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
        row = db.execute(
            "select provider,status from public.connections where tenant_id=%s and id=%s",
            (tenant, connection_id),
        ).fetchone()
    if (
        not row
        or row["status"] == "revoked"
        or (tenant_config and row["provider"] != "fake-crm-http")
    ):
        raise CRMProviderRequestError(
            "Unknown webhook connection", status_code=404, code="connection_unavailable"
        )
    if not secret:
        raise CRMProviderRequestError(
            "Webhook secret unavailable", status_code=503, code="crm_credentials_missing"
        )
    return tenant, secret


@contextmanager
def crm_for(
    settings: Settings,
    tenant: UUID,
    connection_id: UUID | None = None,
    correlation_id: str | None = None,
) -> Iterator[FakeCRMHTTPProvider]:
    if settings.environment not in {"development", "demonstration"}:
        raise CRMProviderRequestError(
            "CRM adapter unavailable", code="client_crm_adapter_not_configured"
        )
    config = settings.crm_connections.get(tenant)
    if config:
        if connection_id is not None and connection_id != config.connection_id:
            raise CRMProviderRequestError(
                "CRM connection mismatch", code="connection_scope_forbidden"
            )
        with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
            row = db.execute(
                "select provider,status from public.connections where tenant_id=%s and id=%s",
                (tenant, config.connection_id),
            ).fetchone()
        if not row or row["provider"] != "fake-crm-http" or row["status"] == "revoked":
            raise CRMProviderRequestError(
                "CRM connection unavailable", code="connection_unavailable"
            )
        secret = os.environ.get(config.api_key_env, "")
        if not secret:
            raise CRMProviderRequestError("CRM secret unavailable", code="crm_credentials_missing")
        base_url = config.base_url
    elif settings.environment == "development" and tenant == settings.tenant_id:
        base_url = settings.fake_crm_base_url
        secret = settings.fake_crm_api_key.get_secret_value()
        if connection_id is not None:
            with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
                row = db.execute(
                    "select 1 from public.connections where tenant_id=%s and id=%s "
                    "and status<>'revoked'",
                    (tenant, connection_id),
                ).fetchone()
            if not row:
                raise CRMProviderRequestError(
                    "CRM connection unavailable", code="connection_scope_forbidden"
                )
    else:
        raise CRMProviderRequestError(
            "CRM adapter unavailable", code="client_crm_adapter_not_configured"
        )
    provider = FakeCRMHTTPProvider(
        base_url, secret, settings.fake_crm_timeout_seconds, correlation_id=correlation_id
    )
    try:
        yield provider
    finally:
        provider.close()


class TenantCRMProvider:
    """Request-scoped facade; each call revalidates the tenant's configured connection."""

    def __init__(self, settings: Settings, tenant: UUID) -> None:
        self.settings, self.tenant = settings, tenant
        self.correlation_id: str | None = None
        self.connection_id: UUID | None = None

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        with crm_for(
            self.settings, self.tenant, self.connection_id, self.correlation_id
        ) as provider:
            return getattr(provider, name)(*args, **kwargs)

    def capabilities(self) -> CRMCapabilities:
        try:
            return CRMCapabilities.model_validate(self._call("capabilities"))
        except CRMProviderRequestError:
            return CRMCapabilities(
                read_deals=False, create_task=False, add_note=False, update_stage=False
            )

    def describe_schema(self) -> dict[str, Any]:
        result: dict[str, Any] = self._call("describe_schema")
        return result

    def list_deals(
        self, cursor: str | None = None, limit: int = 50, changed_after: datetime | None = None
    ) -> CRMDealPage:
        return CRMDealPage.model_validate(self._call("list_deals", cursor, limit, changed_after))

    def create_lead(self, payload: dict[str, Any], idempotency_key: str) -> CRMWriteResult:
        return CRMWriteResult.model_validate(self._call("create_lead", payload, idempotency_key))

    def create_task(self, deal_id: str, title: str, idempotency_key: str) -> CRMWriteResult:
        return CRMWriteResult.model_validate(
            self._call("create_task", deal_id, title, idempotency_key)
        )

    def add_note(self, deal_id: str, body: str, idempotency_key: str) -> CRMWriteResult:
        return CRMWriteResult.model_validate(self._call("add_note", deal_id, body, idempotency_key))

    def update_deal_stage(
        self, deal_id: str, stage: str, idempotency_key: str, expected_version: int | None = None
    ) -> CRMWriteResult:
        return CRMWriteResult.model_validate(
            self._call("update_deal_stage", deal_id, stage, idempotency_key, expected_version)
        )
