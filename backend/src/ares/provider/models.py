from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ares.leads.models import LeadInput


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


class SetPackage(ProviderCommand):
    expected_version: int = Field(ge=1)
    package: Literal["stellar", "ares_connect", "ares_crm", "full_connect", "full_crm"]
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def future_expiry(cls, value: datetime | None) -> datetime | None:
        return SetEntitlement.future_expiry(value)


class SetTenantStatus(ProviderCommand):
    expected_version: int = Field(ge=1)
    status: Literal["active", "suspended"]


class SetInitialAdmin(ProviderCommand):
    expected_version: int = Field(ge=1)
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value: str) -> str:
        result = LeadInput.email_value(value.strip())
        if not result:
            raise ValueError("email_required")
        return result


class TenantRecord(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
    package_code: str | None = None
    package_expires_at: datetime | None = None
    billing_state: str | None = None
    grace_until: date | None = None
    seats_limit: int | None = None


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
    agent_slots: int
    sentinel_slots: int
    ai_daily_budget_brl: Decimal
    ai_monthly_budget_brl: Decimal
    usd_brl_rate: Decimal
    rate_source: str
    updated_at: datetime


class TenantUsageSummary(BaseModel):
    active_members: int
    pending_invitations: int
    ai_spend_today_brl: Decimal
    ai_spend_month_brl: Decimal
    agent_runs_today: int
    agent_runs_month: int


class TenantConfiguration(BaseModel):
    tenant: TenantRecord
    entitlements: list[EntitlementRecord]
    billing: BillingRecord | None = None
    quota: QuotaRecord | None = None
    usage: TenantUsageSummary
    initial_admin_assigned: bool = False
