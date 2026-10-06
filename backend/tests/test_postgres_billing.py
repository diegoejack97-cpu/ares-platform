import os
from datetime import date, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from ares.provider.billing import BillingCommand, billing_status, set_billing
from ares.provider.models import ProviderPrincipal
from ares.provider.service import ProviderConflict, ProviderService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("ARES_TEST_DATABASE_URL"), reason="Postgres required"),
]


def test_billing_grace_release_and_audit():
    url = os.environ["ARES_TEST_DATABASE_URL"]
    tenant, actor, session = uuid4(), uuid4(), uuid4()
    db = psycopg.connect(url, row_factory=dict_row)
    service = ProviderService(url)
    # Share a rollback transaction with the service; no persistent commercial mutations.
    from contextlib import contextmanager

    @contextmanager
    def transaction():
        yield db

    service.db = transaction
    try:
        existing = db.execute(
            "select user_id from private.provider_operators where active"
        ).fetchone()
        if existing:
            actor = existing["user_id"]
        else:
            db.execute("insert into auth.users(id) values(%s)", (actor,))
            db.execute(
                "insert into private.provider_operators(user_id,reason) values(%s,'test')", (actor,)
            )
        db.execute("insert into auth.sessions(id,user_id) values(%s,%s)", (session, actor))
        db.execute(
            "insert into public.tenants(id,name,slug) values(%s,'Billing fixture',%s)",
            (tenant, str(tenant)),
        )
        principal = ProviderPrincipal(actor, session)
        today = date.today()
        with pytest.raises(ProviderConflict):
            set_billing(
                service,
                principal,
                tenant,
                BillingCommand(
                    expected_version=1,
                    state="degraded",
                    due_since=today,
                    grace_until=today,
                    reason="too early",
                ),
            )
        result = set_billing(
            service,
            principal,
            tenant,
            BillingCommand(
                expected_version=1,
                state="past_due",
                due_since=today - timedelta(days=3),
                grace_until=today - timedelta(days=1),
                reason="contract fixture",
            ),
        )
        assert result["version"] == 2
        with pytest.raises(ProviderConflict):
            set_billing(
                service,
                principal,
                tenant,
                BillingCommand(expected_version=1, state="active", reason="stale"),
            )
        result = set_billing(
            service,
            principal,
            tenant,
            BillingCommand(expected_version=2, state="active", reason="payment confirmed"),
        )
        assert result["version"] == 3
        audit = db.execute(
            "select action,before_state,after_state from public.provider_audit "
            "where tenant_id=%s order by id",
            (tenant,),
        ).fetchall()
        assert len(audit) == 2
        assert audit[1]["before_state"]["state"] == "past_due"
        assert audit[1]["after_state"]["state"] == "active"
        # Provider remains authorized independent of customer billing.
        service.authorize(db, principal)
    finally:
        db.rollback()
        db.close()


def test_unconfigured_billing_does_not_invent_a_contract():
    assert billing_status(os.environ["ARES_TEST_DATABASE_URL"], uuid4()) == {
        "state": "unconfigured",
        "degraded": True,
    }
