from datetime import datetime

from pydantic import BaseModel, Field


class CRMCapabilities(BaseModel):
    read_deals: bool = True
    describe_schema: bool = False
    read_changes: bool = False
    create_task: bool = True
    add_note: bool = True
    update_stage: bool = True
    signed_webhooks: bool = False


class CRMDeal(BaseModel):
    id: str
    title: str
    stage: str
    value: float = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    version: int = Field(default=1, ge=1)
    changed_at: datetime | None = None
    owner_id: str | None = None
    synthetic: bool = False
    scenario: str | None = None


class CRMDealPage(BaseModel):
    items: list[CRMDeal]
    next_cursor: str | None = None
    watermark: datetime | None = None


class CRMWriteResult(BaseModel):
    external_id: str
    duplicate: bool = False
