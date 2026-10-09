from datetime import UTC, datetime

import httpx
from fastapi.testclient import TestClient

from ares.connectors.http_fake_crm import CRMProviderRequestError, FakeCRMHTTPProvider
from ares.fake_crm_sandbox.app import app


def make_provider() -> tuple[FakeCRMHTTPProvider, TestClient]:
    client = TestClient(app)

    def handle(request: httpx.Request) -> httpx.Response:
        response = client.request(
            request.method,
            str(request.url),
            headers=dict(request.headers),
            content=request.content,
        )
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )

    provider = FakeCRMHTTPProvider(
        "http://testserver",
        "local-sandbox-key",
        transport=httpx.MockTransport(handle),
    )
    return provider, client


def test_http_adapter_passes_crm_provider_contract() -> None:
    provider, client = make_provider()
    client.post(
        "/v1/admin/reset",
        headers={"Authorization": "Bearer local-sandbox-key"},
    )
    try:
        first_page = provider.list_deals(limit=5)
        second_page = provider.list_deals(cursor=first_page.next_cursor, limit=5)
        changes = provider.list_deals(changed_after=datetime(2026, 8, 25, tzinfo=UTC))
        task = provider.create_task("deal-001", "Retomar proposta", "contract-task-001")
        duplicate = provider.create_task("deal-001", "Retomar proposta", "contract-task-001")
        note = provider.add_note("deal-001", "Cliente respondeu", "contract-note-001")
        stage = provider.update_deal_stage(
            "deal-002",
            "proposal",
            "contract-stage-001",
            expected_version=1,
        )

        assert provider.capabilities().describe_schema is True
        assert provider.describe_schema()["provider"] == "fake-crm-http"
        assert len(first_page.items) == 5
        assert 0 < len(changes.items) < 60
        assert first_page.items[0].id != second_page.items[0].id
        assert first_page.watermark is not None
        assert task.duplicate is False
        assert duplicate.external_id == task.external_id
        assert duplicate.duplicate is True
        assert note.external_id.startswith("note-")
        assert stage.external_id.endswith("v2")
    finally:
        provider.close()
        client.close()


def test_http_adapter_normalizes_provider_errors() -> None:
    client = TestClient(app)

    def handle(request: httpx.Request) -> httpx.Response:
        response = client.request(
            request.method,
            str(request.url),
            headers=dict(request.headers),
            content=request.content,
        )
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )

    provider = FakeCRMHTTPProvider(
        "http://testserver",
        "wrong-key",
        transport=httpx.MockTransport(handle),
    )
    try:
        try:
            provider.list_deals(limit=1)
        except CRMProviderRequestError as error:
            assert error.status_code == 401
            assert error.code == "invalid_api_key"
        else:
            raise AssertionError("provider error was not raised")
    finally:
        provider.close()
        client.close()
