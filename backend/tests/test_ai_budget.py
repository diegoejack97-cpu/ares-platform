import os
from decimal import Decimal
from uuid import UUID

import pytest

from ares.ai.budget import AIBudgetGuard

DATABASE_URL = os.getenv("ARES_TEST_DATABASE_URL")


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="local Supabase database is not configured")
def test_ai_budget_blocks_estimate_above_daily_cap() -> None:
    assert DATABASE_URL is not None
    decision = AIBudgetGuard(DATABASE_URL).check(
        UUID("20000000-0000-0000-0000-000000000001"),
        Decimal("1.01"),
    )

    assert decision.daily_limit_usd == Decimal("1.000000")
    assert decision.allowed is False
    assert decision.warning is True
