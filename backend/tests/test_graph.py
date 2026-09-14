from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ares.graph.projector import node_id, relationships


def test_replay_out_of_order_missing_null_and_invalid_fields():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    events = [
        {"id": uuid4(), "occurred_at": start + timedelta(days=i), "data": data}
        for i, data in enumerate(
            [
                {"company_id": "one", "contact_id": "a"},
                {},
                {"company_id": "two"},
                {"contact_id": None},
                {"company_id": {"bad": True}},
            ]
        )
    ]
    result = relationships(events)
    assert relationships(list(reversed(events))) == result
    assert len(result) == 3
    assert result[0]["valid_until"] == events[2]["occurred_at"]
    assert result[1]["valid_until"] == events[3]["occurred_at"]
    assert result[2]["valid_until"] is None
    assert all(edge["evidence_event_id"] for edge in result)


def test_graph_identity_is_stable_and_tenant_scoped():
    tenant = uuid4()
    assert node_id(tenant, "contact", "one") == node_id(tenant, "contact", "one")
    assert node_id(tenant, "contact", "one") != node_id(uuid4(), "contact", "one")
    assert node_id(tenant, "contact", "one") != node_id(tenant, "company", "one")
