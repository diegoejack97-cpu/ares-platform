import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from test_postgres_command_center import Fixture

from ares.auth.read_scope import read_connection
from ares.config import Settings
from ares.event_journal.service import PostgresEventJournal
from ares.intelligence.service import IntelligenceService
from ares.security.rate_limit import RateLimited, RequestLimiter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("ARES_TEST_DATABASE_URL"), reason="Postgres required"),
]


def test_seller_reads_are_consistent_in_api_analytics_context_and_rls(monkeypatch) -> None:
    import ares.api.app as api

    url = os.environ["ARES_TEST_DATABASE_URL"]
    with psycopg.connect(url, row_factory=dict_row) as db:
        fixture = Fixture(db)
        seller = fixture.user(fixture.seller, "seller")

        @contextmanager
        def injected(*args, **kwargs):
            yield db

        monkeypatch.setattr(psycopg, "connect", injected)
        monkeypatch.setattr(api.settings, "database_url", url)
        api.app.dependency_overrides[api.require_user] = lambda: seller
        try:
            client = TestClient(api.app)
            listing = client.get("/api/v1/opportunities")
            assert listing.status_code == 200
            assert [item["id"] for item in listing.json()["items"]] == [
                str(fixture.opportunities["B"])
            ]
            assert client.get("/api/v1/opportunities/analytics").json()["total"] == 1
            assert (
                client.get(f"/api/v1/opportunities/{fixture.opportunities['A']}").status_code == 404
            )
            assert (
                client.get(
                    f"/api/v1/opportunities/{fixture.opportunities['A']}/context"
                ).status_code
                == 404
            )
            assert (
                client.get("/api/v1/opportunities", params={"owner": str(fixture.manager)}).json()[
                    "items"
                ]
                == []
            )
            with read_connection(url, seller) as scoped:
                for table in ("public.ares_opportunities", "private.portfolio_deals"):
                    assert (
                        scoped.execute(
                            f"select count(*) count from {table} where tenant_id=%s",
                            (fixture.tenant,),
                        ).fetchone()["count"]
                        == 1
                    )
                for table in (
                    "context_snapshots",
                    "ares_interventions",
                    "recommendations",
                    "signals",
                    "commercial_events",
                    "approval_requests",
                    "decisions",
                    "action_executions",
                ):
                    assert (
                        scoped.execute(
                            f"select count(*) count from public.{table} where tenant_id=%s",
                            (fixture.tenant,),
                        ).fetchone()["count"]
                        == 0
                    )
            manager = fixture.user(fixture.manager, "manager")
            assert (
                len(
                    IntelligenceService(
                        url, fixture.tenant, reader=manager
                    )._list_opportunities_sync(None, None, None, None, None, 25)["items"]
                )
                == 4
            )
            # The role carried by a stale principal cannot grant tenant-wide read.
            stale = seller.model_copy(update={"role": "admin"})
            assert (
                IntelligenceService(
                    url, fixture.tenant, reader=stale
                )._opportunity_analytics_sync()["total"]
                == 1
            )
            db.execute(
                "update public.memberships set active=false where tenant_id=%s and user_id=%s",
                (fixture.tenant, fixture.seller),
            )
            assert (
                IntelligenceService(
                    url, fixture.tenant, reader=stale
                )._opportunity_analytics_sync()["total"]
                == 0
            )
        finally:
            api.app.dependency_overrides.clear()
            db.rollback()


def test_journal_pagination_is_bounded_deterministic_and_tenant_scoped(monkeypatch) -> None:
    url = os.environ["ARES_TEST_DATABASE_URL"]
    with psycopg.connect(url, row_factory=dict_row) as db:
        fixture = Fixture(db)
        manager = fixture.user(fixture.manager, "manager")
        event_ids = [uuid4() for _ in range(5)]
        for event_id in event_ids:
            db.execute(
                "insert into public.commercial_events(id,tenant_id,event_type,producer,"
                "aggregate_type,aggregate_id,correlation_id,source,occurred_at,payload_hash,"
                "recorded_at) values(%s,%s,'deal.updated','test','deal','x',%s,'crm',"
                "now(),'synthetic',%s)",
                (event_id, fixture.tenant, fixture.correlation, fixture.now + timedelta(days=1)),
            )

        @contextmanager
        def injected(*args, **kwargs):
            yield db

        monkeypatch.setattr(psycopg, "connect", injected)
        journal = PostgresEventJournal(url, fixture.tenant, reader=manager)
        cursor, collected = None, []
        while True:
            page = journal._list_events_sync(2, cursor)
            assert len(page.items) <= 2
            assert page.total == 8
            collected.extend(item.id for item in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert len(collected) == len(set(collected)) == 8
        assert collected[:5] == sorted(event_ids, reverse=True)
        foreign = manager.model_copy(update={"tenant_id": uuid4()})
        assert (
            PostgresEventJournal(url, fixture.tenant, reader=foreign)._list_events_sync().items
            == []
        )
        db.rollback()


def test_postgres_request_budget_is_shared_between_instances_and_atomic() -> None:
    url = os.environ["ARES_TEST_DATABASE_URL"]
    config = Settings(
        database_url=url, event_journal_backend="postgres", rate_limit_requests_per_minute=5
    )
    user, tenant = uuid4(), uuid4()

    def call(_index):
        limiter = RequestLimiter(config)
        try:
            limiter.enforce(user, tenant, "/api/v1/opportunities", "GET")
            return 200
        except RateLimited:
            return 429

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(call, range(12)))
        assert statuses.count(200) == 5
        assert statuses.count(429) == 7
        # A different tenant has an independent counter.
        RequestLimiter(config).enforce(user, uuid4(), "/api/v1/opportunities", "GET")
    finally:
        import hashlib

        with psycopg.connect(url) as db:
            db.execute(
                "delete from private.api_rate_buckets where key_hash=%s",
                (hashlib.sha256(f"{tenant}:{user}".encode()).hexdigest(),),
            )


def test_internal_scan_and_public_helper_are_not_exposed_to_anonymous() -> None:
    url = os.environ["ARES_TEST_DATABASE_URL"]
    with psycopg.connect(url) as db:
        assert db.execute(
            "select has_function_privilege('anon','public.can_access_tenant(uuid)','EXECUTE')"
        ).fetchone() == (False,)
        assert db.execute(
            "select relrowsecurity from pg_class where oid='public.sentinel_scan_runs'::regclass"
        ).fetchone() == (True,)
        assert db.execute(
            "select has_table_privilege('authenticated','private.api_rate_buckets','SELECT')"
        ).fetchone() == (False,)
