"""Bound requests per verified user across sessions and API processes."""

import hashlib
import math
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any
from uuid import UUID

import psycopg

from ares.config import Settings


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, retry_after)


@dataclass(frozen=True)
class Bucket:
    name: str
    capacity: int
    period: int = 60


class RequestLimiter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = Lock()
        self._memory: dict[tuple[str, str], tuple[float, float]] = {}

    def enforce(self, user_id: UUID, tenant_id: UUID | None, path: str, method: str) -> None:
        identity = hashlib.sha256(f"{tenant_id}:{user_id}".encode()).hexdigest()
        rules = [Bucket("requests", self.settings.rate_limit_requests_per_minute)]
        if method not in {"GET", "HEAD", "OPTIONS"}:
            rules.append(Bucket("writes", self.settings.rate_limit_writes_per_minute))
        if path.startswith("/api/v1/chat") and method == "POST":
            rules.append(Bucket("chat", self.settings.rate_limit_chat_per_minute))
        if self.settings.event_journal_backend == "memory":
            self._consume_memory(identity, rules)
        else:
            self._consume_postgres(identity, rules)

    @staticmethod
    def _remaining(tokens: float, elapsed: float, bucket: Bucket) -> float:
        return min(bucket.capacity, tokens + max(0, elapsed) * bucket.capacity / bucket.period)

    def _consume_memory(self, identity: str, rules: list[Bucket]) -> None:
        now = time.monotonic()
        with self._lock:
            # Memory mode is test/development only. Bound cardinality even there.
            self._memory = {k: v for k, v in self._memory.items() if now - v[1] < 120}
            if len(self._memory) + len(rules) > 8192:
                raise RateLimited(60)
            pending: dict[tuple[str, str], tuple[float, float]] = {}
            for rule in rules:
                key = (identity, rule.name)
                tokens, at = self._memory.get(key, (float(rule.capacity), now))
                tokens = self._remaining(tokens, now - at, rule)
                if tokens < 1:
                    raise RateLimited(math.ceil((1 - tokens) * rule.period / rule.capacity))
                pending[key] = (tokens - 1, now)
            self._memory.update(pending)

    def _consume_postgres(self, identity: str, rules: list[Bucket]) -> None:
        with psycopg.connect(self.settings.database_url) as db:
            db.execute("set local statement_timeout='3s'")
            db.execute("set local lock_timeout='2s'")
            db.execute(
                "delete from private.api_rate_buckets where (key_hash,bucket) in ("
                "select key_hash,bucket from private.api_rate_buckets "
                "where updated_at<clock_timestamp()-interval '1 day' "
                "order by updated_at limit 100 for update skip locked)"
            )
            for rule in rules:
                db.execute(
                    "insert into private.api_rate_buckets(key_hash,bucket,tokens,updated_at) "
                    "values(%s,%s,%s,clock_timestamp()) on conflict do nothing",
                    (identity, rule.name, rule.capacity),
                )
                row: Any = db.execute(
                    "select tokens,extract(epoch from clock_timestamp()-updated_at) "
                    "from private.api_rate_buckets where key_hash=%s and bucket=%s for update",
                    (identity, rule.name),
                ).fetchone()
                assert row is not None
                tokens = self._remaining(float(row[0]), float(row[1]), rule)
                if tokens < 1:
                    # Raising rolls back all buckets for this request.
                    raise RateLimited(math.ceil((1 - tokens) * rule.period / rule.capacity))
                db.execute(
                    "update private.api_rate_buckets set tokens=%s,updated_at=clock_timestamp() "
                    "where key_hash=%s and bucket=%s",
                    (tokens - 1, identity, rule.name),
                )
