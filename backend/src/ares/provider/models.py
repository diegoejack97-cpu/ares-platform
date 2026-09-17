from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


@dataclass(frozen=True)
class ProviderPrincipal:
    user_id: UUID
    session_id: UUID


class ProviderCommand(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    reason: str = Field(min_length=3, max_length=500)


class CreateTenant(ProviderCommand):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SetEntitlement(ProviderCommand):
    expected_version: int = Field(ge=1)
    module: Literal["stellar", "ares_connect", "ares_crm"]
    status: Literal["active", "suspended", "revoked"]
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def future_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value <= datetime.now(UTC)):
            raise ValueError("expiry_must_be_future_and_timezone_aware")
        return value


class TenantRecord(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class TenantPage(BaseModel):
    items: list[TenantRecord]
    next_cursor: UUID | None


class EntitlementRecord(BaseModel):
    module: str
    status: str
    granted_at: datetime
    expires_at: datetime | None


class BillingRecord(BaseModel):
    state: str
    due_since: date | None
    grace_until: date | None
    reason: str
    changed_at: datetime


class QuotaRecord(BaseModel):
    seats_limit: int
    ai_daily_budget_brl: Decimal
    ai_monthly_budget_brl: Decimal
    usd_brl_rate: Decimal
    rate_source: str
    updated_at: datetime


class TenantConfiguration(BaseModel):
    tenant: TenantRecord
    entitlements: list[EntitlementRecord]
    billing: BillingRecord | None = None
    quota: QuotaRecord | None = None
