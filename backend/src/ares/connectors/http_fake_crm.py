from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx

from ares.connectors.models import CRMCapabilities, CRMDeal, CRMDealPage, CRMWriteResult


class CRMProviderRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str = "provider_request_failed",
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after


class FakeCRMHTTPProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 2.0,
        *,
        transport: httpx.BaseTransport | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self._correlation_id = correlation_id
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    @property
    def correlation_id(self) -> str | None:
        return self._correlation_id

    @correlation_id.setter
    def correlation_id(self, value: str | None) -> None:
        # Providers carrying an intent correlation must be request-scoped, not shared.
        self._correlation_id = value

    def capabilities(self) -> CRMCapabilities:
        response = self._request("GET", "/v1/capabilities")
        return CRMCapabilities.model_validate(response.json())

    def describe_schema(self) -> dict[str, Any]:
        response = self._request("GET", "/v1/schema")
        return response.json()

    def get_deal(self, deal_id: str) -> CRMDeal:
        try:
            response = self._request("GET", f"/v1/deals/{deal_id}")
            return CRMDeal.model_validate(response.json())
        except CRMProviderRequestError as error:
            if error.status_code != 404 or error.code != "Not Found":
                raise
        # Older running sandboxes expose only paged reads. Preserve their in-memory data
        # instead of restarting/resetting them merely to obtain a single-record endpoint.
        cursor = None
        for _ in range(20):
            page = self.list_deals(cursor=cursor, limit=100)
            for deal in page.items:
                if deal.id == deal_id:
                    return deal
            cursor = page.next_cursor
            if cursor is None:
                break
        raise CRMProviderRequestError(
            "Source confirmation unavailable", code="deal_not_found", status_code=404
        )

    def list_deals(
        self,
        cursor: str | None = None,
        limit: int = 50,
        changed_after: datetime | None = None,
    ) -> CRMDealPage:
        params: dict[str, str | int] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        if changed_after is not None:
            params["changed_after"] = changed_after.isoformat()
        response = self._request("GET", "/v1/deals", params=params)
        return CRMDealPage.model_validate(response.json())

    def create_task(self, deal_id: str, title: str, idempotency_key: str) -> CRMWriteResult:
        response = self._request(
            "POST",
            f"/v1/deals/{deal_id}/tasks",
            json={"title": title},
            idempotency_key=idempotency_key,
        )
        return CRMWriteResult.model_validate(response.json())

    def add_note(self, deal_id: str, body: str, idempotency_key: str) -> CRMWriteResult:
        response = self._request(
            "POST",
            f"/v1/deals/{deal_id}/notes",
            json={"body": body},
            idempotency_key=idempotency_key,
        )
        return CRMWriteResult.model_validate(response.json())

    def update_deal_stage(
        self,
        deal_id: str,
        stage: str,
        idempotency_key: str,
        expected_version: int | None = None,
    ) -> CRMWriteResult:
        payload: dict[str, Any] = {"stage": stage}
        if expected_version is not None:
            payload["expected_version"] = expected_version
        response = self._request(
            "PATCH",
            f"/v1/deals/{deal_id}/stage",
            json=payload,
            idempotency_key=idempotency_key,
        )
        return CRMWriteResult.model_validate(response.json())

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        headers = {"X-Correlation-Id": self._correlation_id or str(uuid4())}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json,
                headers=headers,
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
        return response
