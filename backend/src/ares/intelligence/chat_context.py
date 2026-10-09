"""Deterministic Context Builder projection for the scoped conversational reader."""

import hashlib
import json
from typing import Any


def bounded_context(snapshot: dict[str, Any], byte_budget: int = 2500) -> dict[str, Any]:
    # UTF-8 byte count is a conservative token upper bound, not a provider token count.
    facts = snapshot["facts"]
    payload: dict[str, Any] = {"deal": {}, "events": []}
    for key in ("id", "title", "status", "value", "currency"):
        value = facts.get("deal", {}).get(key)
        if value is not None:
            payload["deal"][key] = str(value)[:120]
    citations = []
    selected_ids = set()

    def encode() -> str:
        return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))

    for event in facts.get("events", []):
        entry = {key: event.get(key) for key in ("id", "event_type", "occurred_at", "data")}
        payload["events"].append(entry)
        if len(encode().encode("utf-8")) > byte_budget:
            payload["events"].pop()
            continue
        selected_ids.add(str(event.get("id")))
    for citation in snapshot.get("citations", []):
        if str(citation.get("event_id")) in selected_ids:
            citations.append(citation)
    encoded = encode()
    if len(encoded.encode("utf-8")) > byte_budget:
        raise ValueError("context_budget_too_small")
    return {
        "context_ref": str(snapshot["context_ref"]),
        "content": encoded,
        "content_hash": hashlib.sha256(encoded.encode()).hexdigest(),
        "tokens_upper_bound": len(encoded.encode("utf-8")),
        "token_limit": byte_budget,
        "count_method": "utf8_bytes_upper_bound",
        "citations": citations,
        "truncated": len(selected_ids) < len(facts.get("events", [])),
        "captured_at": snapshot["captured_at"],
        "source": "Event Journal",
    }
