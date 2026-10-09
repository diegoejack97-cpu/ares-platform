import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ares.intelligence.context_builder import project
from ares.intelligence.queries import QueryIntent, intent_from_question


@pytest.mark.parametrize("extra", ["sql", "tenant_id", "model_id", "facts", "role"])
def test_query_rejects_untrusted_scope_or_sql(extra):
    with pytest.raises(ValidationError):
        QueryIntent.model_validate({extra: "select *"})


def test_period_requires_timezone_and_complete_bounded_interval():
    now = datetime.now(UTC)
    for payload in [
        {"since": now},
        {"since": now.replace(tzinfo=None), "until": now},
        {"since": now, "until": now - timedelta(days=1)},
        {"since": now - timedelta(days=367), "until": now},
    ]:
        with pytest.raises(ValidationError):
            QueryIntent.model_validate(payload)


def test_question_compiles_to_typed_filters_without_guessing_sql():
    intent = intent_from_question("qual o total de oportunidades em negociação BRL?")
    assert intent.stages == ["negotiation"] and intent.currency == "BRL"
    assert intent.name is None and intent.since is None
    assert intent_from_question("quantas oportunidades temos hoje?").since is None
    assert intent_from_question("quantos negócios criados hoje?").date_field == "created"
    assert intent_from_question("qual a melhor oportunidade?").open_only


def test_projection_records_multibyte_cuts_and_keeps_exact_totals():
    payload = {
        "matches": [{"id": str(i), "title": "ação " * 80} for i in range(20)],
        "metrics": {"total": 100, "currencies": [{"currency": "BRL", "value": "0.00"}]},
    }
    projected, cuts = project(payload)
    assert len(json.dumps(projected, ensure_ascii=False, separators=(",", ":")).encode()) <= 2000
    assert cuts and projected["metrics"] == payload["metrics"]
    assert len(payload["matches"]) == 20
