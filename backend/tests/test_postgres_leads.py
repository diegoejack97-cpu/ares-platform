import os
from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from ares.auth.models import AuthenticatedUser
from ares.connectors.fake_crm import FakeCRMProvider
from ares.connectors.models import CRMCapabilities, CRMWriteResult
from ares.fake_crm_sandbox.store import SandboxStore
from ares.integrations.service import IntegrationError
from ares.leads.models import LeadInput, LeadResolve
from ares.leads.service import LeadService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("ARES_TEST_DATABASE_URL"), reason="Postgres required"),
]


def test_triage_create_merge_undo_and_isolation():
    class Provider(FakeCRMProvider):
        def __init__(self):
            self.store = SandboxStore()

        def capabilities(self):
            return CRMCapabilities(create_lead=True)

        def create_lead(self, payload, idempotency_key):
            return CRMWriteResult.model_validate(
                self.store.create_lead(payload, idempotency_key).model_dump()
            )

    url = os.environ["ARES_TEST_DATABASE_URL"]
    provider = Provider()
    service = LeadService(url, provider)
    db = psycopg.connect(url, row_factory=dict_row)

    @contextmanager
    def transaction():
        yield db

    service.db = transaction
    try:
        tenant = UUID("20000000-0000-0000-0000-000000000001")
        member = db.execute(
            "select user_id from public.memberships where tenant_id=%s and role='admin' "
            "and active limit 1",
            (tenant,),
        ).fetchone()
        assert member
        user = AuthenticatedUser(user_id=member["user_id"], tenant_id=tenant, role="admin")
        command = LeadInput(
            name="Synthetic M6", email=f"{uuid4()}@example.test", idempotency_key=uuid4()
        )
        first = service.intake(user, command)
        assert service.intake(user, command)["id"] == first["id"]
        with pytest.raises(IntegrationError):
            service.intake(user, command.model_copy(update={"name": "Different"}))
        created = service.resolve_locked(
            user,
            first["id"],
            LeadResolve(action="create", expected_version=1, reason="test create"),
        )
        assert created["status"] == "created" and created["external_id"]
        second = service.intake(user, command.model_copy(update={"idempotency_key": uuid4()}))
        matches = service.candidates(user, second["id"])
        assert any(
            row["id"] == created["target_subject_id"] and row["score"] == 1 for row in matches
        )
        merged = service.resolve_locked(
            user,
            second["id"],
            LeadResolve(
                action="merge",
                target_subject_id=created["target_subject_id"],
                expected_version=1,
                reason="same identity",
            ),
        )
        assert merged["status"] == "merged"
        undone = service.resolve_locked(
            user,
            second["id"],
            LeadResolve(action="undo", expected_version=merged["version"], reason="review again"),
        )
        assert undone["status"] == "pending" and undone["target_subject_id"] is None
        assert len(provider.store.leads) == 1
        with pytest.raises(IntegrationError):
            service.candidates(user.model_copy(update={"tenant_id": uuid4()}), first["id"])
        with pytest.raises(IntegrationError):
            service.candidates(user.model_copy(update={"role": "auditor"}), first["id"])
    finally:
        db.rollback()
        db.close()
