import base64
import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from ares.connectors.http_fake_crm import CRMProviderRequestError, FakeCRMHTTPProvider
from ares.fake_crm_sandbox.app import app
from ares.fake_crm_sandbox.store import SandboxConflict, SandboxStore


def test_snapshot_pagination_survives_concurrent_stage_changes() -> None:
    store = SandboxStore()
    original = {item.id: item.version for item in store.deals.values()}
    first, cursor, watermark = store.list_deals(None, 7, None)
    assert cursor is not None and watermark is not None
    consumed = first[0]
    remaining = next(item for item in store.deals.values() if item.id not in {d.id for d in first})
    store.update_stage(consumed.id, "won", consumed.version, "concurrent-consumed")
    store.update_stage(remaining.id, "lost", remaining.version, "concurrent-unseen")
    seen = first[:]
    retry, _, retry_watermark = store.list_deals(cursor, 7, None)
    while cursor:
        page, cursor, page_watermark = store.list_deals(cursor, 7, None)
        assert page_watermark == watermark
        seen.extend(page)
    assert seen[7:14] == retry
    assert retry_watermark == watermark
    assert len(seen) == len(original) == len({item.id for item in seen})
    assert {item.id: item.version for item in seen} == original
    changes, _, _ = store.list_deals(None, 100, watermark)
    changed_versions = {item.id: item.version for item in changes}
    assert changed_versions[consumed.id] == consumed.version + 1
    assert changed_versions[remaining.id] == remaining.version + 1


def test_watermark_ties_are_replayed_and_paged_without_omissions() -> None:
    store = SandboxStore()
    tied = datetime(2026, 9, 1, tzinfo=UTC)
    store.deals = {
        key: item.model_copy(update={"changed_at": tied}) for key, item in store.deals.items()
    }
    seen = []
    cursor = None
    while True:
        page, cursor, watermark = store.list_deals(cursor, 9, tied)
        assert watermark == tied
        seen.extend(item.id for item in page)
        if cursor is None:
            break
    assert len(seen) == 60
    assert seen == sorted(store.deals)


@pytest.mark.parametrize("cursor", ["!!!", "e30=", "WyJhIiwgMSwgImIiXQ==", "b2Zmc2V0OjE="])
def test_malformed_cursors_are_rejected(cursor: str) -> None:
    with pytest.raises(SandboxConflict, match="invalid_cursor"):
        SandboxStore().list_deals(cursor, 10, None)


def test_expired_cursor_and_changed_filters_fail_explicitly() -> None:
    store = SandboxStore()
    _, cursor, _ = store.list_deals(None, 1, None)
    assert cursor is not None
    with pytest.raises(SandboxConflict, match="cursor_filter_mismatch"):
        store.list_deals(cursor, 1, datetime(2026, 9, 1, tzinfo=UTC))
    snapshot_id = json.loads(base64.urlsafe_b64decode(cursor))[0]
    store._snapshots[snapshot_id] = replace(store._snapshots[snapshot_id], expires_at=0)
    with pytest.raises(SandboxConflict, match="snapshot_expired"):
        store.list_deals(cursor, 1, None)


def test_stage_confirmation_is_versioned_and_idempotent() -> None:
    store = SandboxStore()
    before = store.get_deal("deal-001")
    result = store.update_stage(before.id, "won", before.version, "intent-001")
    duplicate = store.update_stage(before.id, "won", before.version, "intent-001")
    after = store.get_deal(before.id)
    assert after.stage == "won" and after.version == before.version + 1
    assert duplicate.duplicate and duplicate.external_id == result.external_id
    with pytest.raises(SandboxConflict, match="version_conflict"):
        store.update_stage(before.id, "lost", before.version, "intent-002")
    with pytest.raises(SandboxConflict, match="idempotency_key_reused"):
        store.update_stage(before.id, "lost", after.version, "intent-001")
    assert store.get_deal(before.id) == after


def test_http_provider_reuses_intent_correlation_and_reads_confirmed_state() -> None:
    observed: list[httpx.Request] = []
    deal = SandboxStore().get_deal("deal-001")

    def handle(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json=deal.model_dump(mode="json"), request=request)

    provider = FakeCRMHTTPProvider(
        "http://testserver",
        "synthetic-key",
        correlation_id="intent-correlation",
        transport=httpx.MockTransport(handle),
    )
    try:
        provider.correlation_id = "intent-correlation"
        assert provider.correlation_id == "intent-correlation"
        assert provider.get_deal(deal.id).version == deal.version
        assert provider.get_deal(deal.id).stage == deal.stage
        assert all(
            request.headers["X-Correlation-Id"] == "intent-correlation" for request in observed
        )
        assert observed[0].url.path == "/v1/deals/deal-001"
    finally:
        provider.close()


def test_single_deal_endpoint_requires_auth_and_returns_no_synthetic_missing_deal() -> None:
    with TestClient(app) as client:
        assert client.get("/v1/deals/deal-001").status_code == 401
        headers = {"Authorization": "Bearer local-sandbox-key", "X-Correlation-Id": "read-test"}
        found = client.get("/v1/deals/deal-001", headers=headers)
        assert found.status_code == 200 and found.json()["id"] == "deal-001"
        assert found.headers["X-Correlation-Id"] == "read-test"
        absent = client.get("/v1/deals/not-a-deal", headers=headers)
        assert absent.status_code == 404
        assert absent.json()["detail"]["code"] == "deal_not_found"


def test_provider_preserves_rate_limit_retry_after() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"detail": {"code": "rate_limited"}},
            headers={"Retry-After": "7"},
            request=request,
        )

    provider = FakeCRMHTTPProvider(
        "http://testserver", "key", transport=httpx.MockTransport(handle)
    )
    try:
        with pytest.raises(CRMProviderRequestError) as failure:
            provider.get_deal("deal-001")
        assert failure.value.status_code == 429
        assert failure.value.retry_after == "7"
        assert failure.value.code == "rate_limited"
    finally:
        provider.close()


@pytest.mark.parametrize("include_nulls", [True, False])
def test_http_provider_preserves_missing_money_without_inventing_zero(include_nulls: bool) -> None:
    raw = SandboxStore().get_deal("deal-001").model_dump(mode="json")
    raw.pop("value")
    raw.pop("currency")
    if include_nulls:
        raw.update(value=None, currency=None)

    def handle(request: httpx.Request) -> httpx.Response:
        payload = raw if request.url.path.endswith("deal-001") else {"items": [raw]}
        return httpx.Response(200, json=payload, request=request)

    provider = FakeCRMHTTPProvider(
        "http://testserver", "key", transport=httpx.MockTransport(handle)
    )
    try:
        deal = provider.get_deal("deal-001")
        page = provider.list_deals()
        assert deal.value is None and deal.currency is None
        assert page.items[0].value is None and page.items[0].currency is None
    finally:
        provider.close()
