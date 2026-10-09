import json

from ares.intelligence.chat_context import bounded_context


def test_context_cites_only_included_events_and_bounds_multibyte_input():
    snapshot = {
        "context_ref": "synthetic",
        "captured_at": "2026-09-14",
        "facts": {
            "deal": {"title": "Teste"},
            "events": [
                {"id": "huge", "data": {"text": "漢" * 3000}},
                {"id": "small", "event_type": "deal.updated", "data": {"value": 20}},
            ],
        },
        "citations": [{"event_id": "huge"}, {"event_id": "small"}],
    }
    context = bounded_context(snapshot)
    assert context["tokens_upper_bound"] <= 2500 and context["truncated"]
    assert context["citations"] == [{"event_id": "small"}]
    assert len(json.loads(context["content"])["events"]) == 1
    assert bounded_context(snapshot)["content_hash"] == context["content_hash"]
