import hashlib
import hmac
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException, status
from pydantic import ValidationError

from ares.connectors.models import CRMCapabilities, CRMDeal, CRMDealPage, CRMWriteResult
from ares.event_journal.models import IncomingCRMEvent


class FakeCRMProvider:
    def __init__(self, webhook_secret: str) -> None:
        self._secret = webhook_secret.encode()
        self._lock = Lock()
        self._deals = [
            CRMDeal(
                id="deal-001",
                title="Renovação Serra Metais",
                stage="proposal",
                value=125000,
                currency="BRL",
            ),
            CRMDeal(
                id="deal-002",
                title="Expansão Vale Norte",
                stage="qualification",
                value=78000,
                currency="BRL",
            ),
        ]
        self._writes: dict[str, CRMWriteResult] = {}

    def capabilities(self) -> CRMCapabilities:
        return CRMCapabilities()

    def list_deals(self, cursor: str | None = None, limit: int = 50) -> CRMDealPage:
        start = int(cursor or "0")
        items = self._deals[start : start + limit]
        next_offset = start + len(items)
        next_cursor = str(next_offset) if next_offset < len(self._deals) else None
        return CRMDealPage(items=items, next_cursor=next_cursor)

    def create_task(self, deal_id: str, title: str, idempotency_key: str) -> CRMWriteResult:
        return self._write("task", deal_id, title, idempotency_key)

    def add_note(self, deal_id: str, body: str, idempotency_key: str) -> CRMWriteResult:
        return self._write("note", deal_id, body, idempotency_key)

    def update_deal_stage(self, deal_id: str, stage: str, idempotency_key: str) -> CRMWriteResult:
        with self._lock:
            existing = self._writes.get(idempotency_key)
            if existing is not None:
                return existing.model_copy(update={"duplicate": True})
            for index, deal in enumerate(self._deals):
                if deal.id == deal_id:
                    self._deals[index] = deal.model_copy(update={"stage": stage})
                    result = CRMWriteResult(external_id=f"stage-{uuid4()}")
                    self._writes[idempotency_key] = result
                    return result
        raise ValueError(f"Unknown deal: {deal_id}")

    def _write(self, kind: str, deal_id: str, content: str, idempotency_key: str) -> CRMWriteResult:
        if not content.strip():
            raise ValueError(f"{kind} content must not be empty")
        if not deal_id.startswith("deal-"):
            raise ValueError(f"Unknown deal: {deal_id}")
        with self._lock:
            existing = self._writes.get(idempotency_key)
            if existing is not None:
                return existing.model_copy(update={"duplicate": True})
            result = CRMWriteResult(external_id=f"{kind}-{uuid4()}")
            self._writes[idempotency_key] = result
            return result

    def sign(self, raw_body: bytes) -> str:
        digest = hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def verify_and_normalize(
        self,
        raw_body: bytes,
        signature: str | None,
    ) -> IncomingCRMEvent:
        expected = self.sign(raw_body)
        if signature is None or not hmac.compare_digest(signature, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid FakeCRM webhook signature",
            )
        try:
            return IncomingCRMEvent.model_validate_json(raw_body)
        except ValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error.errors(include_url=False),
            ) from error
