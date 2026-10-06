import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from ares.connectors.http_fake_crm import CRMProviderRequestError


class FakeCRMLabClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 2.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._transport = transport

    async def snapshot(self) -> dict[str, Any]:
        health, capabilities, stages, deals, state = await asyncio.gather(
            self._request("GET", "/health", authenticated=False),
            self._request("GET", "/v1/capabilities"),
            self._request("GET", "/v1/stages"),
            self._request("GET", "/v1/deals", params={"limit": 100}),
            self._request("GET", "/v1/admin/state"),
        )
        return {
            "health": health,
            "capabilities": capabilities,
            "stages": stages["items"],
            "deals": deals["items"],
            "counts": state["counts"],
            "watermark": deals.get("watermark"),
            "freshness_at": datetime.now(UTC).isoformat(),
            "source": "FakeCRM HTTP Sandbox",
            "docs_url": f"{self._base_url}/docs",
        }

    async def get_deal(self, deal_id: str) -> dict[str, Any]:
        deals = await self._request("GET", "/v1/deals", params={"limit": 100})
        deal = next((item for item in deals["items"] if item["id"] == deal_id), None)
        if deal is None:
            raise CRMProviderRequestError(
                f"FakeCRM deal not found: {deal_id}",
                status_code=404,
                code="deal_not_found",
            )
        return dict(deal)

    async def reset(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/admin/reset")

    async def create_task(self, deal_id: str, title: str, idempotency_key: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/deals/{deal_id}/tasks",
            json={"title": title},
            idempotency_key=idempotency_key,
        )

    async def add_note(self, deal_id: str, body: str, idempotency_key: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/deals/{deal_id}/notes",
            json={"body": body},
            idempotency_key=idempotency_key,
        )

    async def update_stage(
        self,
        deal_id: str,
        stage: str,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._request(
            "PATCH",
            f"/v1/deals/{deal_id}/stage",
            json={"stage": stage, "expected_version": expected_version},
            idempotency_key=idempotency_key,
        )

    async def simulate_fault(self, scenario: str) -> dict[str, Any]:
        try:
            await self._request(
                "GET",
                "/v1/deals",
                headers={"X-FakeCRM-Scenario": scenario},
            )
        except CRMProviderRequestError as error:
            return {
                "scenario": scenario,
                "observed": True,
                "status_code": error.status_code,
                "code": error.code,
                "retry_after": error.retry_after,
            }
        return {
            "scenario": scenario,
            "observed": False,
            "status_code": 200,
            "code": "no_fault_observed",
            "retry_after": None,
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        params: dict[str, str | int] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        request_headers = dict(headers or {})
        if authenticated:
            request_headers["Authorization"] = f"Bearer {self._api_key}"
        if idempotency_key is not None:
            request_headers["Idempotency-Key"] = idempotency_key
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=request_headers,
                )
        except httpx.TimeoutException as error:
            raise CRMProviderRequestError(
                "FakeCRM Sandbox timed out",
                code="provider_timeout",
            ) from error
        except httpx.RequestError as error:
            raise CRMProviderRequestError(str(error)) from error
        if response.is_error:
            detail: Any
            try:
                detail = response.json().get("detail", {})
            except ValueError:
                detail = {}
            code = (
                detail.get("code", "provider_request_failed")
                if isinstance(detail, dict)
                else str(detail)
            )
            raise CRMProviderRequestError(
                f"FakeCRM Sandbox returned HTTP {response.status_code}: {code}",
                status_code=response.status_code,
                code=code,
                retry_after=response.headers.get("Retry-After"),
            )
        return dict(response.json())
