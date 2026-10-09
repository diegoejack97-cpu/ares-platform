import os
from uuid import UUID, uuid4

import pytest

from ares.auth.models import AuthenticatedUser
from ares.impact.models import ImpactPage, ImpactSummary
from ares.impact.service import ImpactDenied, ImpactService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("ARES_TEST_DATABASE_URL"), reason="Postgres required"),
]


def test_impact_source_and_role_isolation():
    import psycopg

    url = os.environ["ARES_TEST_DATABASE_URL"]
    tenant = UUID("20000000-0000-0000-0000-000000000001")
    with psycopg.connect(url) as db:
        row = db.execute(
            "select user_id from public.memberships where tenant_id=%s and active and "
            "role='admin' limit 1",
            (tenant,),
        ).fetchone()
    assert row
    user = AuthenticatedUser(user_id=row[0], tenant_id=tenant, role="admin")
    service = ImpactService(url)
    summary = ImpactSummary.model_validate(service.summary(user))
    assert summary.ai_cost.measured_runs <= summary.ai_cost.runs
    ImpactPage.model_validate(service.interventions(user))
    with pytest.raises(ImpactDenied):
        service.summary(user.model_copy(update={"tenant_id": uuid4()}))
    with pytest.raises(ImpactDenied):
        service.summary(user.model_copy(update={"role": "seller"}))
