import base64
import hashlib
import json
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from ares.fake_crm_sandbox.models import SandboxDeal, SandboxWriteResult
from ares.fake_crm_sandbox.seed import STAGES, build_seed


class SandboxConflict(ValueError):
    pass


class SandboxNotFound(ValueError):
    pass


class SandboxStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    def reset(self) -> dict[str, int]:
        seed = build_seed()
        with getattr(self, "_lock", Lock()):
            self.companies = list(seed["companies"])
            self.contacts = list(seed["contacts"])
            self.deals = {deal.id: deal for deal in seed["deals"] if isinstance(deal, SandboxDeal)}
            self.activities = list(seed["activities"])
            self.tasks: list[dict[str, Any]] = []
            self.notes: list[dict[str, Any]] = []
            self._idempotency: dict[str, tuple[str, SandboxWriteResult]] = {}
        return self.counts()

    def counts(self) -> dict[str, int]:
        return {
            "companies": len(self.companies),
            "contacts": len(self.contacts),
            "deals": len(self.deals),
            "activities": len(self.activities),
            "tasks": len(self.tasks),
            "notes": len(self.notes),
        }

    def list_deals(
        self,
        cursor: str | None,
        limit: int,
        changed_after: datetime | None,
    ) -> tuple[list[SandboxDeal], str | None, datetime | None]:
        offset = self._decode_cursor(cursor) if cursor else 0
        ordered = sorted(self.deals.values(), key=lambda item: (item.changed_at, item.id))
        if changed_after is not None:
            ordered = [item for item in ordered if item.changed_at > changed_after]
        items = ordered[offset : offset + limit]
        next_offset = offset + len(items)
        next_cursor = self._encode_cursor(next_offset) if next_offset < len(ordered) else None
        watermark = max((item.changed_at for item in ordered), default=None)
        return items, next_cursor, watermark

    def write(
        self,
        kind: str,
        deal_id: str,
        content: str,
        idempotency_key: str,
    ) -> SandboxWriteResult:
        if deal_id not in self.deals:
            raise SandboxNotFound(deal_id)
        fingerprint = self._fingerprint(kind, deal_id, content)
        with self._lock:
            prior = self._idempotency.get(idempotency_key)
            if prior is not None:
                if prior[0] != fingerprint:
                    raise SandboxConflict("idempotency_key_reused_with_different_payload")
                return prior[1].model_copy(update={"duplicate": True})
            target = self.tasks if kind == "task" else self.notes
            external_id = f"{kind}-{len(target) + 1:04d}"
            target.append(
                {
                    "id": external_id,
                    "deal_id": deal_id,
                    "content": content,
                    "created_at": datetime.now(UTC).isoformat(),
                    "synthetic": True,
                }
            )
            result = SandboxWriteResult(external_id=external_id)
            self._idempotency[idempotency_key] = (fingerprint, result)
            return result

    def update_stage(
        self,
        deal_id: str,
        stage: str,
        expected_version: int | None,
        idempotency_key: str,
    ) -> SandboxWriteResult:
        if stage not in STAGES:
            raise SandboxConflict("invalid_stage")
        deal = self.deals.get(deal_id)
        if deal is None:
            raise SandboxNotFound(deal_id)
        fingerprint = self._fingerprint("stage", deal_id, stage, expected_version)
        with self._lock:
            prior = self._idempotency.get(idempotency_key)
            if prior is not None:
                if prior[0] != fingerprint:
                    raise SandboxConflict("idempotency_key_reused_with_different_payload")
                return prior[1].model_copy(update={"duplicate": True})
            current = self.deals[deal_id]
            if expected_version is not None and current.version != expected_version:
                raise SandboxConflict("version_conflict")
            self.deals[deal_id] = current.model_copy(
                update={
                    "stage": stage,
                    "version": current.version + 1,
                    "changed_at": datetime.now(UTC),
                }
            )
            result = SandboxWriteResult(external_id=f"stage-{deal_id}-v{current.version + 1}")
            self._idempotency[idempotency_key] = (fingerprint, result)
            return result

    @staticmethod
    def _fingerprint(*values: Any) -> str:
        raw = json.dumps(values, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _encode_cursor(offset: int) -> str:
        return base64.urlsafe_b64encode(f"offset:{offset}".encode()).decode()

    @staticmethod
    def _decode_cursor(cursor: str) -> int:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode()).decode()
            prefix, value = raw.split(":", maxsplit=1)
            if prefix != "offset":
                raise ValueError
            return int(value)
        except (ValueError, UnicodeDecodeError) as error:
            raise SandboxConflict("invalid_cursor") from error
