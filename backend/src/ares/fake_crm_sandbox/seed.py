from datetime import UTC, datetime, timedelta
from typing import Any

from ares.fake_crm_sandbox.models import SandboxDeal

ANCHOR = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
STAGES = ["new", "qualification", "proposal", "negotiation", "won", "lost"]
SCENARIOS = [
    "follow_up_overdue",
    "proposal_stalled",
    "no_owner",
    "customer_replied",
    "duplicate_candidate",
    "healthy_pipeline",
    "won_after_intervention",
    "lost_no_response",
]


def build_seed() -> dict[str, list[dict[str, Any]] | list[SandboxDeal]]:
    companies = [
        {
            "id": f"company-{index:03d}",
            "name": f"Empresa Sintética {index:03d}",
            "synthetic": True,
        }
        for index in range(1, 21)
    ]
    contacts = [
        {
            "id": f"contact-{index:03d}",
            "name": f"Contato Exemplo {index:03d}",
            "email": f"contato{index:03d}@example.test",
            "company_id": f"company-{((index - 1) % 20) + 1:03d}",
            "synthetic": True,
        }
        for index in range(1, 41)
    ]
    deals: list[SandboxDeal] = []
    activities: list[dict[str, Any]] = []
    for index in range(1, 61):
        scenario = SCENARIOS[(index - 1) % len(SCENARIOS)]
        stage = STAGES[(index - 1) % len(STAGES)]
        changed_at = ANCHOR - timedelta(days=(index * 3) % 120, hours=index % 12)
        owner_id = None if scenario == "no_owner" else f"seller-{((index - 1) % 6) + 1:02d}"
        deal = SandboxDeal(
            id=f"deal-{index:03d}",
            title=f"Oportunidade Sintética {index:03d}",
            stage=stage,
            value=float(15000 + index * 2750),
            changed_at=changed_at,
            owner_id=owner_id,
            company_id=f"company-{((index - 1) % 20) + 1:03d}",
            contact_id=f"contact-{((index - 1) % 40) + 1:03d}",
            scenario=scenario,
        )
        deals.append(deal)
        activities.append(
            {
                "id": f"activity-{index:03d}",
                "deal_id": deal.id,
                "kind": "email" if index % 2 else "call",
                "occurred_at": (changed_at - timedelta(days=index % 9)).isoformat(),
                "direction": "inbound" if scenario == "customer_replied" else "outbound",
                "synthetic": True,
            }
        )
    return {
        "companies": companies,
        "contacts": contacts,
        "deals": deals,
        "activities": activities,
    }
