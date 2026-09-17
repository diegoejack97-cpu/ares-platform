import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from ares.provider.models import CreateTenant, ProviderPrincipal, SetEntitlement
from ares.provider.service import ProviderConflict, ProviderDenied, ProviderService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("ARES_TEST_DATABASE_URL"), reason="Postgres required"),
]


@pytest.fixture
def provider():
    db = psycopg.connect(os.environ["ARES_TEST_DATABASE_URL"], row_factory=dict_row)
    actor, session = uuid4(), uuid4()
    existing = db.execute("select user_id from private.provider_operators where active").fetchone()
    if existing:
        actor = existing["user_id"]
    else:
        db.execute("insert into auth.users(id) values(%s)", (actor,))
        db.execute(
            "insert into private.provider_operators(user_id,reason) values(%s,'test')", (actor,)
        )
    db.execute("insert into auth.sessions(id,user_id) values(%s,%s)", (session, actor))
    principal = ProviderPrincipal(user_id=actor, session_id=session)
    try:
        yield db, principal, ProviderService("")
    finally:
        db.rollback()
        db.close()


def test_create_entitlement_conflict_and_immutable_audit(provider):
    db, actor, service = provider
    tenant = service.create_on(
        db, actor, CreateTenant(name="Test", slug=str(uuid4()), reason="test")
    )
    target = tenant["id"]
    change = SetEntitlement(
        module="ares_connect", status="active", expected_version=1, reason="contract"
    )
    result = service.entitle_on(db, actor, target, change)
    assert result["version"] == 2
    with pytest.raises(ProviderConflict), db.transaction():
        service.entitle_on(db, actor, target, change)
    with pytest.raises(ProviderConflict), db.transaction():
        service.entitle_on(
            db,
            actor,
            target,
            SetEntitlement(
                module="ares_crm", status="active", expected_version=2, reason="invalid migration"
            ),
        )
    service.entitle_on(
        db,
        actor,
        target,
        SetEntitlement(
            module="ares_connect", status="suspended", expected_version=2, reason="suspend module"
        ),
    )
    # Suspension is not permission to silently switch funnel owner.
    with pytest.raises(ProviderConflict), db.transaction():
        service.entitle_on(
            db,
            actor,
            target,
            SetEntitlement(
                module="ares_crm", status="active", expected_version=3, reason="invalid migration"
            ),
        )
    audit = db.execute(
        "select * from public.provider_audit where tenant_id=%s order by id", (target,)
    ).fetchall()
    assert [row["action"] for row in audit] == [
        "tenant.create",
        "entitlement.set",
        "entitlement.set",
    ]
    assert audit[1]["before_state"]["version"] == 1
    assert audit[1]["after_state"]["version"] == 2
    with pytest.raises(psycopg.errors.RaiseException), db.transaction():
        db.execute("delete from public.provider_audit where tenant_id=%s", (target,))
    db.execute("set local role authenticated")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("select * from private.provider_operators")
    assert db.execute("select count(*) n from public.provider_audit").fetchone()["n"] == 0
    db.execute("reset role")


def test_revoked_session_or_membership_denies_provider(provider):
    db, actor, service = provider
    service.authorize(db, actor)
    db.execute("delete from auth.sessions where id=%s", (actor.session_id,))
    with pytest.raises(ProviderDenied):
        service.authorize(db, actor)
    db.execute(
        "insert into auth.sessions(id,user_id) values(%s,%s)", (actor.session_id, actor.user_id)
    )
    tenant = uuid4()
    db.execute(
        "insert into public.tenants(id,name,slug) values(%s,'test',%s)", (tenant, str(tenant))
    )
    db.execute(
        "insert into public.memberships(tenant_id,user_id,role,active) values(%s,%s,'admin',false)",
        (tenant, actor.user_id),
    )
    with pytest.raises(ProviderDenied):
        service.authorize(db, actor)
