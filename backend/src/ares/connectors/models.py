from pydantic import BaseModel, Field


class CRMCapabilities(BaseModel):
    read_deals: bool = True
    create_task: bool = True
    add_note: bool = True
    update_stage: bool = True


class CRMDeal(BaseModel):
    id: str
    title: str
    stage: str
    value: float = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class CRMDealPage(BaseModel):
    items: list[CRMDeal]
    next_cursor: str | None = None


class CRMWriteResult(BaseModel):
    external_id: str
    duplicate: bool = False
