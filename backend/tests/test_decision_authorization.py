from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from ares.connectors.fake_crm import FakeCRMProvider
from ares.decision.authorization import role_can_decide
from ares.decision.service import DecisionService


@pytest.mark.parametrize("role", ["admin", "manager", "seller", "auditor", "unknown", None])
@pytest.mark.parametrize("required", ["admin", "manager", "seller", "unknown", None])
def test_approval_role_matrix_fails_closed(role: str | None, required: str | None) -> None:
    authorized_pairs = {
        ("admin", "admin"),
        ("admin", "manager"),
        ("admin", "seller"),
        ("manager", "manager"),
        ("manager", "seller"),
        ("seller", "seller"),
    }
    assert role_can_decide(role, required) is ((role, required) in authorized_pairs)


@pytest.mark.parametrize("approval_status", ["approved", "expired", "superseded"])
def test_resolved_approval_never_advertises_decision_permission(approval_status: str) -> None:
    service = DecisionService("", UUID(int=1), FakeCRMProvider("synthetic"))
    result = service._decision_permissions(
        {
            "status": "pending",
            "approval_status": approval_status,
            "approval_required_role": "manager",
            "approval_expires_at": datetime.now(UTC) + timedelta(hours=1),
            "policy_verdict": "require_approval",
            "recommended_action": {"action_kind": "create_task", "payload": {"title": "Test"}},
        },
        "admin",
        str(UUID(int=2)),
    )
    assert result["can_decide"] is False
