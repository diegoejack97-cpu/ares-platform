"""A bounded per-process guard before authentication or webhook body reads.

Uses the ASGI peer only, never an untrusted X-Forwarded-For value. The durable
authenticated-user limiter remains the authoritative cross-process control.
"""

import hashlib
import math
import time
from threading import Lock
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class TrafficLimitMiddleware:
    def __init__(self, app: ASGIApp, requests_per_minute: int = 600) -> None:
        self.app, self.capacity = app, requests_per_minute
        self._peers: dict[str, tuple[float, float]] = {}
        self._lock = Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return
        peer = (scope.get("client") or ("unknown", 0))[0]
        key = hashlib.sha256(peer.encode()).hexdigest()
        now, retry = time.monotonic(), 0
        with self._lock:
            self._peers = {k: v for k, v in self._peers.items() if now - v[1] < 120}
            if key not in self._peers and len(self._peers) >= 4096:
                retry = 60
            else:
                tokens, at = self._peers.get(key, (float(self.capacity), now))
                tokens = min(self.capacity, tokens + max(0, now - at) * self.capacity / 60)
                if tokens < 1:
                    retry = math.ceil((1 - tokens) * 60 / self.capacity)
                else:
                    self._peers[key] = (tokens - 1, now)
        if retry:
            correlation = str(uuid4())
            response = JSONResponse(
                {"detail": {"code": "request_rate_limited", "correlation_id": correlation}},
                status_code=429,
                headers={
                    "Retry-After": str(max(1, retry)),
                    "Cache-Control": "no-store",
                    "X-Correlation-Id": correlation,
                },
            )
            await response(scope, receive, send)
        else:
            await self.app(scope, receive, send)
