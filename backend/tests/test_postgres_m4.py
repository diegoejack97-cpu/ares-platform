"""M4 acceptance against real SQL, isolated tenant, always rolled back."""

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from ares.auth.models import AuthenticatedUser
from ares.connectors.models import CRMCapabilities, CRMDeal, CRMDealPage, CRMWriteResult
from ares.fake_crm_sandbox.store import SandboxStore
from ares.integrations.models import MappingCommand, StageCommand, SyncCommand, suggested_mapping
from ares.integrations.pipeline import PipelineService
from ares.integrations.service import IntegrationError

DATABASE_URL = os.getenv("ARES_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="local PostgreSQL not configured"),
]


class IsolatedProvider:
    def __init__(self):
        self.store = SandboxStore()
        self.write_count = 0

    def capabilities(self):
        return CRMCapabilities(describe_schema=True, read_changes=True)

    def describe_schema(self):
        return {"deal_fields": [f["provider_path"] for f in suggested_mapping()["fields"]]}

    def list_deals(self, cursor=None, limit=50, changed_after=None):
        items, cursor, watermark = self.store.list_deals(cursor, limit, changed_after)
        return CRMDealPage(
            items=[CRMDeal.model_validate(i.model_dump()) for i in items],
            next_cursor=cursor,
            watermark=watermark,
        )

    def get_deal(self, deal_id):
        return CRMDeal.model_validate(self.store.deals[deal_id].model_dump())

    def update_deal_stage(self, deal_id, stage, idempotency_key, expected_version=None):
        self.write_count += 1
        result = self.store.update_stage(deal_id, stage, expected_version, idempotency_key)
        return CRMWriteResult.model_validate(result.model_dump())


@pytest.fixture
def setup_m4():
    assert DATABASE_URL
    db = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    tenant, actor = uuid4(), uuid4()
    db.execute("insert into auth.users(id) values(%s)", (actor,))
    db.execute(
        "insert into public.tenants(id,name,slug) values(%s,'M4 isolated test',%s)",
        (tenant, str(tenant)),
    )
    db.execute(
        "insert into public.memberships(tenant_id,user_id,role) values(%s,%s,'admin')",
        (tenant, actor),
    )
    db.execute(
        "insert into public.tenant_entitlements(tenant_id,module,status,granted_by) "
        "values(%s,'ares_connect','active',%s)",
        (tenant, actor),
    )
    provider = IsolatedProvider()

    class TestService(PipelineService):
        @contextmanager
        def db(self):
            with db.transaction():
                yield db

    service = TestService(DATABASE_URL, tenant, provider)
    user = AuthenticatedUser(user_id=actor, tenant_id=tenant, role="admin")
    service.save_mapping(
        user, MappingCommand.model_validate({"expected_version": 0, **suggested_mapping()})
    )
    try:
        yield db, service, provider, user
    finally:
        db.rollback()
        db.close()


def finish(db, service, job):
    for _ in range(20):
        service.process_job(job)
        job = db.execute("select * from public.jobs where id=%s", (job["id"],)).fetchone()
        if job["status"] == "succeeded":
            return job
    raise AssertionError("sync did not complete")


def test_sync_checkpoint_replay_reconcile_history_and_human_write(setup_m4):
    db, service, provider, user = setup_m4
    job = service.enqueue(user, SyncCommand(mode="reconcile"))
    service.process_job(job)
    assert (
        db.execute(
            "select count(*) as n from public.deals where tenant_id=%s", (user.tenant_id,)
        ).fetchone()["n"]
        == 25
    )
    assert not db.execute(
        "select * from public.sync_cursors where tenant_id=%s", (user.tenant_id,)
    ).fetchone()
    resumed = db.execute("select * from public.jobs where id=%s", (job["id"],)).fetchone()
    finish(db, service, resumed)
    assert len(service.pipeline(user)["items"]) == 60
    checkpoint = db.execute(
        "select watermark from public.sync_cursors where tenant_id=%s", (user.tenant_id,)
    ).fetchone()["watermark"]
    count = db.execute(
        "select count(*) as n from public.commercial_events where tenant_id=%s", (user.tenant_id,)
    ).fetchone()["n"]
    finish(db, service, service.enqueue(user, SyncCommand(mode="reconcile")))
    assert (
        db.execute(
            "select count(*) as n from public.commercial_events where tenant_id=%s",
            (user.tenant_id,),
        ).fetchone()["n"]
        == count
    )
    removed = next(iter(provider.store.deals))
    del provider.store.deals[removed]
    finish(db, service, service.enqueue(user, SyncCommand(mode="reconcile")))
    assert service.pipeline(user)["missing_count"] == 1
    until = datetime.now(UTC)
    finish(
        db,
        service,
        service.enqueue(
            user, SyncCommand(mode="historical", since=until - timedelta(days=90), until=until)
        ),
    )
    assert (
        db.execute(
            "select watermark from public.sync_cursors where tenant_id=%s", (user.tenant_id,)
        ).fetchone()["watermark"]
        == checkpoint
    )
    deal = next(i for i in service.pipeline(user)["items"] if not i["is_missing"])
    target = "proposal" if deal["stage"] != "proposal" else "negotiation"
    command = StageCommand(
        stage=target, expected_version=deal["version"], idempotency_key=uuid4(), confirmed=True
    )
    result = service._move_locked(user, deal["id"], command)
    assert result["status"] == "succeeded" and result["ares_intervention"] is False
    assert service._move_locked(user, deal["id"], command)["duplicate"]
    assert provider.write_count == 1
    with pytest.raises(IntegrationError, match="idempotency_key_reused"):
        service._move_locked(user, deal["id"], command.model_copy(update={"stage": "won"}))
    assert (
        db.execute(
            "select count(*) as n from public.deal_stage_history where tenant_id=%s",
            (user.tenant_id,),
        ).fetchone()["n"]
        == 1
    )
    assert (
        db.execute(
            "select count(*) as n from public.audit_log where tenant_id=%s", (user.tenant_id,)
        ).fetchone()["n"]
        == 2
    )


def test_mapping_is_optimistic_and_module_exclusive(setup_m4):
    db, service, _, user = setup_m4
    with pytest.raises(IntegrationError, match="mapping_version_conflict"):
        service.save_mapping(
            user, MappingCommand.model_validate({"expected_version": 0, **suggested_mapping()})
        )
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction():
        db.execute(
            "insert into public.tenant_entitlements(tenant_id,module,status,granted_by) "
            "values(%s,'ares_crm','active',%s)",
            (user.tenant_id, user.user_id),
        )


def test_rls_membership_entitlement_and_client_write_denial(setup_m4):
    db, service, _, user = setup_m4
    finish(db, service, service.enqueue(user, SyncCommand(mode="reconcile")))
    tables = [
        "field_mappings",
        "stage_mappings",
        "external_records",
        "sync_cursors",
        "connection_schema_snapshots",
        "external_write_dedup",
        "deal_stage_history",
        "audit_log",
    ]
    db.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(user.user_id),))
    db.execute(
        "select set_config('request.jwt.claims',%s,true)",
        (
            json.dumps(
                {
                    "sub": str(user.user_id),
                    "app_metadata": {"active_tenant_id": str(user.tenant_id)},
                }
            ),
        ),
    )
    db.execute("set local role authenticated")
    assert len(db.execute("select * from public.external_records").fetchall()) == 60
    for table in tables:
        for privilege in ["INSERT", "UPDATE", "DELETE"]:
            assert not db.execute(
                "select has_table_privilege(current_user,%s,%s) as ok",
                (f"public.{table}", privilege),
            ).fetchone()["ok"]
    db.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(uuid4()),))
    db.execute(
        "select set_config('request.jwt.claims',%s,true)",
        (
            json.dumps(
                {"sub": str(uuid4()), "app_metadata": {"active_tenant_id": str(user.tenant_id)}}
            ),
        ),
    )
    assert not db.execute("select * from public.external_records").fetchall()
    db.execute("reset role")
    db.execute(
        "update public.tenant_entitlements set status='suspended' where tenant_id=%s",
        (user.tenant_id,),
    )
    with pytest.raises(IntegrationError, match="entitlement_required"):
        service.pipeline(user)
    db.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(user.user_id),))
    db.execute(
        "select set_config('request.jwt.claims',%s,true)",
        (
            json.dumps(
                {
                    "sub": str(user.user_id),
                    "app_metadata": {"active_tenant_id": str(user.tenant_id)},
                }
            ),
        ),
    )
    db.execute("set local role authenticated")
    assert not db.execute("select * from public.external_records").fetchall()
    # Canonical deals are API-only in the existing schema (no direct browser SELECT grant).
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("select * from public.deals where tenant_id=%s", (user.tenant_id,))
    db.execute("set local role anon")
    assert not db.execute(
        "select has_table_privilege(current_user,'public.external_records','SELECT') as ok"
    ).fetchone()["ok"]
    db.execute("reset role")
