import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import Any
from uuid import uuid4

from ares.fake_crm_sandbox.models import SandboxDeal, SandboxWriteResult
from ares.fake_crm_sandbox.seed import STAGES, build_seed


class SandboxConflict(ValueError):
    pass


class SandboxNotFound(ValueError):
    pass


@dataclass(frozen=True)
class DealSnapshot:
    items: tuple[SandboxDeal, ...]
    changed_after: datetime | None
    watermark: datetime | None
    expires_at: float


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
            self._snapshots: dict[str, DealSnapshot] = {}
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
        if not 1 <= limit <= 100:
            raise SandboxConflict("invalid_page_size")
        if changed_after is not None and changed_after.tzinfo is None:
            raise SandboxConflict("timezone_required")
        with self._lock:
            now = monotonic()
            self._snapshots = {
                key: value for key, value in self._snapshots.items() if value.expires_at > now
            }
            if cursor:
                snapshot_id, after = self._decode_cursor(cursor)
                snapshot = self._snapshots.get(snapshot_id)
                if snapshot is None:
                    raise SandboxConflict("snapshot_expired")
                if snapshot.changed_after != changed_after:
                    raise SandboxConflict("cursor_filter_mismatch")
            else:
                snapshot_id, after = str(uuid4()), None
                # Snapshot copies keep reconciliation stable when records change between pages.
                # Inclusive watermarks replay ties; the consumer deduplicates versions.
                ordered = tuple(
                    item.model_copy(deep=True)
                    for item in sorted(
                        self.deals.values(), key=lambda item: (item.changed_at, item.id)
                    )
                    if changed_after is None or item.changed_at >= changed_after
                )
                snapshot = DealSnapshot(
                    items=ordered,
                    changed_after=changed_after,
                    watermark=max((item.changed_at for item in ordered), default=None),
                    expires_at=now + 3600,
                )
                if len(self._snapshots) >= 128:
                    oldest = min(self._snapshots, key=lambda key: self._snapshots[key].expires_at)
                    del self._snapshots[oldest]
                self._snapshots[snapshot_id] = snapshot
            remaining = [
                item
                for item in snapshot.items
                if after is None or (item.changed_at, item.id) > after
            ]
            items = remaining[:limit]
            next_cursor = (
                self._encode_cursor(snapshot_id, items[-1]) if len(remaining) > limit else None
            )
            return [item.model_copy(deep=True) for item in items], next_cursor, snapshot.watermark

    def get_deal(self, deal_id: str) -> SandboxDeal:
        with self._lock:
            deal = self.deals.get(deal_id)
            if deal is None:
                raise SandboxNotFound(deal_id)
            return deal.model_copy(deep=True)

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
    def _encode_cursor(snapshot_id: str, last: SandboxDeal) -> str:
        raw = json.dumps([snapshot_id, last.changed_at.isoformat(), last.id]).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[str, tuple[datetime, str]]:
        try:
            values = json.loads(base64.b64decode(cursor.encode(), altchars=b"-_", validate=True))
            if not isinstance(values, list) or len(values) != 3:
                raise ValueError
            if not all(isinstance(value, str) for value in values):
                raise ValueError
            snapshot_id, changed_at, deal_id = values
            timestamp = datetime.fromisoformat(changed_at)
            if timestamp.tzinfo is None:
                raise ValueError
            return snapshot_id, (timestamp, deal_id)
        except (ValueError, UnicodeDecodeError, TypeError) as error:
            raise SandboxConflict("invalid_cursor") from error
