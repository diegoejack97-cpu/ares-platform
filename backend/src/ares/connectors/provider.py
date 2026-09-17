from datetime import datetime
from typing import Any, Protocol

from ares.connectors.models import CRMCapabilities, CRMDealPage, CRMWriteResult
from ares.event_journal.models import IncomingCRMEvent


class CRMProvider(Protocol):
    def create_lead(self, payload: dict[str, Any], idempotency_key: str) -> CRMWriteResult: ...

    def capabilities(self) -> CRMCapabilities: ...

    def describe_schema(self) -> dict[str, Any]: ...

    def list_deals(
        self,
        cursor: str | None = None,
        limit: int = 50,
        changed_after: datetime | None = None,
    ) -> CRMDealPage: ...

    def create_task(self, deal_id: str, title: str, idempotency_key: str) -> CRMWriteResult: ...

    def add_note(self, deal_id: str, body: str, idempotency_key: str) -> CRMWriteResult: ...

    def update_deal_stage(
        self,
        deal_id: str,
        stage: str,
        idempotency_key: str,
        expected_version: int | None = None,
    ) -> CRMWriteResult: ...


class CRMWebhookProvider(Protocol):
    def sign(self, raw_body: bytes) -> str: ...

    def verify_and_normalize(self, raw_body: bytes, signature: str | None) -> IncomingCRMEvent: ...
