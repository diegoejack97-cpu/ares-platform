from uuid import uuid4

import pytest
from pydantic import ValidationError

from ares.fake_crm_sandbox.store import SandboxConflict, SandboxStore
from ares.leads.models import LeadInput, normalize_name


def test_identity_normalization_and_required_contact():
    command = LeadInput(
        name="  Ána Silva ",
        email="ANA@example.test",
        phone="+55 (11) 99999-0000",
        idempotency_key=uuid4(),
    )
    assert command.email == "ana@example.test"
    assert command.phone == "5511999990000"
    assert normalize_name(command.name) == "ana silva"
    with pytest.raises(ValidationError):
        LeadInput(name="Ana", idempotency_key=uuid4())


def test_source_lead_idempotency_and_payload_conflict():
    store = SandboxStore()
    payload = {"name": "Synthetic lead", "email": "lead@example.test", "phone": None}
    first = store.create_lead(payload, "stable-key")
    replay = store.create_lead(payload, "stable-key")
    assert replay.external_id == first.external_id and replay.duplicate
    assert len(store.leads) == 1
    with pytest.raises(SandboxConflict):
        store.create_lead({**payload, "name": "Changed"}, "stable-key")
