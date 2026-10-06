"""Independent HTTP sources with colliding IDs must stay scoped to their company."""

import json
import os
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4

import psycopg
import pytest

from ares.config import CRMConnectionSettings, Settings
from ares.connectors.http_fake_crm import CRMProviderRequestError
from ares.connectors.resolver import crm_for, webhook_for

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("ARES_TEST_DATABASE_URL"), reason="isolated PostgreSQL required"
    ),
]


@contextmanager
def source(name, secret):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.headers.get("Authorization"))
            authorized = self.headers.get("Authorization") == f"Bearer {secret}"
            self.send_response(200 if authorized else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "same-external-id",
                                "title": name,
                                "stage": "proposal",
                                "value": 100,
                            }
                        ],
                        "next_cursor": None,
                    }
                ).encode()
            )

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_two_company_sources_and_webhook_secrets_never_fall_back(monkeypatch):
    url = os.environ["ARES_TEST_DATABASE_URL"]
    tenants, connections = [uuid4(), uuid4()], [uuid4(), uuid4()]
    with psycopg.connect(url) as db:
        for tenant, connection in zip(tenants, connections, strict=True):
            db.execute(
                "insert into public.tenants(id,name,slug) values(%s,'Synthetic routing',%s)",
                (tenant, str(tenant)),
            )
            db.execute(
                "insert into public.connections(id,tenant_id,provider) "
                "values(%s,%s,'fake-crm-http')",
                (connection, tenant),
            )
    try:
        with (
            source("Synthetic company A", "synthetic-a") as (base_a, calls_a),
            source("Synthetic company B", "synthetic-b") as (base_b, calls_b),
        ):
            monkeypatch.setenv("ARES_CRM_SECRET_TEST_A", "synthetic-a")
            monkeypatch.setenv("ARES_CRM_SECRET_TEST_B", "synthetic-b")
            monkeypatch.setenv("ARES_CRM_SECRET_HMAC_A", "synthetic-hmac-a")
            monkeypatch.setenv("ARES_CRM_SECRET_HMAC_B", "synthetic-hmac-b")
            settings = Settings(
                _env_file=None,
                database_url=url,
                tenant_id=tenants[0],
                crm_connections={
                    tenant: CRMConnectionSettings(
                        connection_id=connection,
                        base_url=base,
                        api_key_env=f"ARES_CRM_SECRET_TEST_{suffix}",
                        webhook_secret_env=f"ARES_CRM_SECRET_HMAC_{suffix}",
                    )
                    for tenant, connection, base, suffix in zip(
                        tenants, connections, [base_a, base_b], ["A", "B"], strict=True
                    )
                },
            )
            for tenant, name in zip(
                tenants, ["Synthetic company A", "Synthetic company B"], strict=True
            ):
                with crm_for(settings, tenant) as provider:
                    assert provider.list_deals().items[0].title == name
            assert calls_a == ["Bearer synthetic-a"] and calls_b == ["Bearer synthetic-b"]
            assert webhook_for(settings, connections[1]) == (tenants[1], "synthetic-hmac-b")
            with (
                pytest.raises(CRMProviderRequestError, match="mismatch"),
                crm_for(settings, tenants[0], connections[1]),
            ):
                pytest.fail("cross-company dispatch accepted")
            with pytest.raises(CRMProviderRequestError), crm_for(settings, uuid4()):
                pytest.fail("unknown company inherited a CRM")
            with psycopg.connect(url) as db:
                db.execute(
                    "update public.connections set status='revoked' where id=%s", (connections[1],)
                )
            with pytest.raises(CRMProviderRequestError):
                webhook_for(settings, connections[1])
            with pytest.raises(CRMProviderRequestError), crm_for(settings, tenants[1]):
                pytest.fail("revoked connection dispatched")
            assert len(calls_a) == len(calls_b) == 1
    finally:
        with psycopg.connect(url) as db:
            for tenant in tenants:
                db.execute("delete from public.connections where tenant_id=%s", (tenant,))
                db.execute("delete from public.sentinel_schedules where tenant_id=%s", (tenant,))
                db.execute("delete from public.tenants where id=%s", (tenant,))
