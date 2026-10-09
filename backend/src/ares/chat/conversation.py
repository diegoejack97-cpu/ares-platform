"""Bounded references from this user's conversation, never historical facts as evidence."""

import json
import re
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from ares.auth.models import AuthenticatedUser
from ares.chat.search import normalize


def recent_turns(
    database_url: str, user: AuthenticatedUser, scope: UUID | None, finding: UUID | None = None
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as db:
        rows = db.execute(
            "select m.user_text,m.context_json from public.messages m "
            "join public.conversations c on c.tenant_id=m.tenant_id and c.id=m.conversation_id "
            "where c.tenant_id=%s and c.owner_user_id=%s "
            "and c.opportunity_id is not distinct from %s "
            "and c.finding_id is not distinct from %s and m.status='succeeded' "
            "and m.created_at>now()-interval '24 hours' "
            "order by m.created_at desc,m.id desc limit 3",
            (user.tenant_id, user.user_id, scope, finding),
        ).fetchall()
    return [dict(row) for row in rows]


def conversation_reference(
    turns: list[dict[str, Any]], question: str
) -> tuple[list[str] | None, dict[str, Any]]:
    words = normalize(question)
    followup = bool(
        re.search(
            r"\b(dessas?|dess[ea]s?|essas?|eles|elas|del[ae]s?|primeir[ao]|segund[ao]|terceir[ao])\b",
            words,
        )
        or re.match(r"\s*e\b", words)
        or re.fullmatch(r"\s*por\s*que[?!\s]*", words)
    )
    if not followup:
        return None, {}
    for turn in turns:
        context = turn.get("context_json") or {}
        try:
            payload = json.loads(context.get("content", "{}"))
        except (ValueError, TypeError):
            continue
        matches = payload.get("matches", [])[:8]
        if not matches:
            continue
        previous_reference = context.get("conversation_reference") or {}
        selected = payload.get("selection") or previous_reference.get("selected_record_reference")
        ordinal = next(
            (i for i, term in enumerate(("primeir", "segund", "terceir")) if term in words),
            None,
        )
        if ordinal is not None:
            matches = matches[ordinal : ordinal + 1]
        elif (
            re.search(r"\b(essa|dessa|ela|dela|dele)\b", words)
            and selected
            and not re.search(r"\bpor\s*que\b", words)
        ):
            matches = [
                m
                for m in matches
                if record_ref(m) == selected or selected in m.get("record_ids", [])
            ]
        references = list(
            dict.fromkeys(
                str(ref)[:160]
                for item in matches
                for ref in [record_ref(item), *item.get("record_ids", [])]
                if ref is not None
            )
        )[:24]
        return references, {
            "previous_question": str(turn.get("user_text", ""))[:500],
            "record_references": references,
            "previous_criterion": payload.get("criterion")
            or previous_reference.get("previous_criterion"),
            "selected_record_reference": selected,
            "use": "Referências da conversa; fatos consultados novamente nas fontes autorizadas.",
        }
    return None, {}


def record_ref(item: dict[str, Any]) -> str | None:
    ref = item.get("id") or item.get("external_id") or item.get("opportunity_id")
    return str(ref)[:160] if ref is not None else None
