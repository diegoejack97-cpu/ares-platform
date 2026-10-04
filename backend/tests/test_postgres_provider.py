import os
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from ares.provider.models import (
    CreateTenant,
    ProviderPrincipal,
    SetEntitlement,
    SetInitialAdmin,
    SetPackage,
    SetTenantStatus,
)
from ares.provider.quotas import QuotaCommand, set_quota
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


def test_provider_assigns_package_and_releases_only_configured_company(provider):
    db, actor, service = provider
    tenant = service.create_on(
        db, actor, CreateTenant(name="Plano Teste", slug=str(uuid4()), reason="Novo contrato")
    )
    target = tenant["id"]
    assert tenant["status"] == "suspended"
    with pytest.raises(ProviderConflict), db.transaction():
        service.set_status_on(
            db,
            actor,
            target,
            SetTenantStatus(status="active", expected_version=1, reason="Liberar empresa"),
        )
    expires_at = datetime.now(UTC) + timedelta(days=30)
    package = service.assign_package_on(
        db,
        actor,
        target,
        SetPackage(
            package="full_connect",
            expires_at=expires_at,
            expected_version=1,
            reason="Plano contratado",
        ),
    )
    assert package["version"] == 2
    modules = db.execute(
        "select module,expires_at from public.tenant_entitlements "
        "where tenant_id=%s order by module",
        (target,),
    ).fetchall()
    assert [item["module"] for item in modules] == ["ares_connect", "stellar"]
    assert all(item["expires_at"] == expires_at for item in modules)
    with pytest.raises(ProviderConflict), db.transaction():
        service.set_status_on(
            db,
            actor,
            target,
            SetTenantStatus(status="active", expected_version=2, reason="Liberar empresa"),
        )
    db.execute(
        "insert into public.tenant_quotas(tenant_id,seats_limit,ai_daily_budget_brl,"
        "ai_monthly_budget_brl,usd_brl_rate,rate_source,updated_by) "
        "values(%s,10,5,50,5,'Contrato teste',%s)",
        (target, actor.user_id),
    )
    db.execute(
        "insert into public.tenant_billing_state(tenant_id,state,reason,changed_by) "
        "values(%s,'active','Contrato teste',%s)",
        (target, actor.user_id),
    )
    with pytest.raises(ProviderConflict), db.transaction():
        service.set_status_on(
            db,
            actor,
            target,
            SetTenantStatus(status="active", expected_version=2, reason="Liberar empresa"),
        )
    first_admin = uuid4()
    db.execute(
        "insert into auth.users(id,email,email_confirmed_at) values(%s,%s,now())",
        (first_admin, f"admin-{first_admin}@example.test"),
    )
    appointed = service.assign_initial_admin_on(
        db,
        actor,
        target,
        SetInitialAdmin(
            email=f"admin-{first_admin}@example.test",
            expected_version=2,
            reason="Administrador do contrato",
        ),
    )
    assert appointed["version"] == 3
    released = service.set_status_on(
        db,
        actor,
        target,
        SetTenantStatus(status="active", expected_version=3, reason="Liberar empresa"),
    )
    assert released["status"] == "active"
    assert released["version"] == 4
    audit = db.execute(
        "select action from public.provider_audit where tenant_id=%s order by id", (target,)
    ).fetchall()
    assert [entry["action"] for entry in audit] == [
        "tenant.create",
        "package.assign",
        "tenant.initial_admin",
        "tenant.status",
    ]


def test_provider_sets_and_preserves_routine_capacity_with_audit(provider):
    db, actor, service = provider
    tenant = service.create_on(
        db, actor, CreateTenant(name="Capacidade", slug=str(uuid4()), reason="Novo contrato")
    )
    service.db = lambda: nullcontext(db)
    common = {
        "seats_limit": 3,
        "ai_daily_budget_brl": 5,
        "ai_monthly_budget_brl": 50,
        "usd_brl_rate": 5,
        "rate_source": "Contrato de teste",
        "reason": "Capacidade contratada",
    }
    first = set_quota(
        service,
        actor,
        tenant["id"],
        QuotaCommand(expected_version=1, agent_slots=0, sentinel_slots=2, **common),
    )
    assert first["version"] == 2
    second = set_quota(
        service,
        actor,
        tenant["id"],
        QuotaCommand(expected_version=2, **common),
    )
    assert second["version"] == 3
    capacity = db.execute(
        "select agent_slots,sentinel_slots from public.tenant_quotas where tenant_id=%s",
        (tenant["id"],),
    ).fetchone()
    assert (capacity["agent_slots"], capacity["sentinel_slots"]) == (0, 2)
    actions = db.execute(
        "select action from public.provider_audit where tenant_id=%s order by id",
        (tenant["id"],),
    ).fetchall()
    assert [row["action"] for row in actions] == ["tenant.create", "quota.set", "quota.set"]
