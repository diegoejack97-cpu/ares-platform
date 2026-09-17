# SQL strings remain complete for review.
# ruff: noqa: E501
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.auth.models import AuthenticatedUser
from ares.connectors.provider import CRMProvider
from ares.integrations.service import IntegrationError
from ares.leads.models import LeadInput, LeadResolve, normalize_name
from ares.provider.billing import billing_status


class LeadService:
    def __init__(self, url: str, provider: CRMProvider):
        self.url, self.provider = url, provider

    @contextmanager
    def db(self) -> Iterator[psycopg.Connection[Any]]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            db.execute("set local statement_timeout='10s'")
            yield db

    def authorize(self, db: psycopg.Connection[Any], user: AuthenticatedUser) -> None:
        if (
            user.role not in {"admin", "manager", "seller"}
            or not db.execute(
                "select 1 from public.memberships m join public.tenant_entitlements e on e.tenant_id=m.tenant_id "
                "where m.tenant_id=%s and m.user_id=%s and m.active and m.role in ('admin','manager','seller') "
                "and e.module='ares_connect' and e.status='active' and (e.expires_at is null or e.expires_at>now())",
                (user.tenant_id, user.user_id),
            ).fetchone()
        ):
            raise IntegrationError("lead_unavailable", 404)

    def row(self, db: psycopg.Connection[Any], user: AuthenticatedUser, id: UUID) -> dict[str, Any]:
        self.authorize(db, user)
        row = db.execute(
            "select * from public.lead_intake where tenant_id=%s and id=%s and (%s or owner_id=%s) for update",
            (user.tenant_id, id, user.role in {"admin", "manager"}, user.user_id),
        ).fetchone()
        if not row:
            raise IntegrationError("lead_unavailable", 404)
        return dict(row)

    def audit(
        self,
        db: psycopg.Connection[Any],
        user: AuthenticatedUser,
        row: dict[str, Any],
        action: str,
        reason: str,
    ) -> None:
        db.execute(
            "insert into public.audit_log(tenant_id,actor_type,actor_id,action,correlation_id,source,data) values(%s,'human',%s,%s,%s,'ares:leads',%s)",
            (
                user.tenant_id,
                user.user_id,
                action,
                row["correlation_id"],
                Jsonb({"lead_id": str(row["id"]), "version": row["version"], "reason": reason}),
            ),
        )

    def listing(self, user: AuthenticatedUser, cursor: UUID | None = None) -> dict[str, Any]:
        with self.db() as db:
            self.authorize(db, user)
            rows = db.execute(
                "select * from public.lead_intake where tenant_id=%s and (%s or owner_id=%s) and (%s::uuid is null or id>%s) order by id limit 26",
                (user.tenant_id, user.role in {"admin", "manager"}, user.user_id, cursor, cursor),
            ).fetchall()
        return {
            "items": rows[:25],
            "next_cursor": rows[24]["id"] if len(rows) > 25 else None,
            "can_create": self.provider.capabilities().create_lead,
        }

    def intake(self, user: AuthenticatedUser, command: LeadInput) -> dict[str, Any]:
        fingerprint = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
        with self.db() as db:
            self.authorize(db, user)
            db.execute(
                "select pg_advisory_xact_lock(hashtext(%s))",
                (f"intake:{user.tenant_id}:{command.idempotency_key}",),
            )
            prior = db.execute(
                "select * from public.lead_intake where tenant_id=%s and idempotency_key=%s",
                (user.tenant_id, command.idempotency_key),
            ).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint or prior["owner_id"] != user.user_id:
                    raise IntegrationError("idempotency_conflict", 409)
                return dict(prior)
            row = db.execute(
                "insert into public.lead_intake(tenant_id,owner_id,name,email,phone,identity_hash,idempotency_key,fingerprint) values(%s,%s,%s,%s,%s,%s,%s,%s) returning *",
                (
                    user.tenant_id,
                    user.user_id,
                    command.name,
                    command.email,
                    command.phone,
                    command.identity_hash(),
                    command.idempotency_key,
                    fingerprint,
                ),
            ).fetchone()
            assert row
            self.audit(db, user, row, "lead.intake", "Human submitted lead for triage")
            return dict(row)

    def candidates_on(
        self, db: psycopg.Connection[Any], user: AuthenticatedUser, row: dict[str, Any]
    ) -> list[dict[str, Any]]:
        candidates = db.execute(
            "select s.id,s.display_name,s.external_ref from public.subjects s where s.tenant_id=%s and (%s or exists(select 1 from public.deals d where d.tenant_id=s.tenant_id and d.subject_id=s.id and d.owner_user_id=%s) or exists(select 1 from public.lead_intake l where l.tenant_id=s.tenant_id and l.target_subject_id=s.id and l.owner_id=%s)) order by s.id",
            (user.tenant_id, user.role in {"admin", "manager"}, user.user_id, user.user_id),
        ).fetchall()
        matches = []
        for item in candidates:
            ref = item["external_ref"] or {}
            reasons = []
            score = SequenceMatcher(
                None, normalize_name(row["name"]), normalize_name(item["display_name"])
            ).ratio()
            if score >= 0.75:
                reasons.append("Nome semelhante")
            if row["email"] and row["email"] == str(ref.get("email", "")).casefold():
                score = 1
                reasons.append("E-mail idêntico")
            if row["phone"] and row["phone"] == ref.get("phone"):
                score = 1
                reasons.append("Telefone idêntico")
            if reasons:
                matches.append(
                    {
                        "id": item["id"],
                        "display_name": item["display_name"],
                        "score": round(score, 3),
                        "reasons": reasons,
                    }
                )
        return sorted(matches, key=lambda i: (-i["score"], str(i["id"])))[:20]

    def candidates(self, user: AuthenticatedUser, id: UUID) -> list[dict[str, Any]]:
        with self.db() as db:
            return self.candidates_on(db, user, self.row(db, user, id))

    def resolve(self, user: AuthenticatedUser, id: UUID, command: LeadResolve) -> dict[str, Any]:
        if billing_status(self.url, user.tenant_id)["degraded"]:
            raise IntegrationError("billing_degraded", 403)
        # The session lock spans CRM I/O; the write intent commits before the external call.
        with psycopg.connect(self.url, autocommit=True) as guard:
            key = f"lead-resolve:{user.tenant_id}"
            acquired = guard.execute("select pg_try_advisory_lock(hashtext(%s))", (key,)).fetchone()
            if not acquired or not acquired[0]:
                raise IntegrationError("write_in_progress", 409)
            try:
                return self.resolve_locked(user, id, command)
            finally:
                guard.execute("select pg_advisory_unlock(hashtext(%s))", (key,))

    def resolve_locked(
        self, user: AuthenticatedUser, id: UUID, command: LeadResolve
    ) -> dict[str, Any]:
        with self.db() as db:
            row = self.row(db, user, id)
            if row["version"] != command.expected_version:
                raise IntegrationError("version_conflict", 409)
            if command.action == "undo":
                if row["status"] != "merged":
                    raise IntegrationError("merge_not_active", 409)
                db.execute(
                    "update public.merge_operations set undone_at=now(),undone_by=%s where tenant_id=%s and lead_id=%s and undone_at is null",
                    (user.user_id, user.tenant_id, id),
                )
                state, target = "pending", None
            else:
                if row["status"] not in {"pending", "uncertain", "creating"}:
                    raise IntegrationError("lead_already_resolved", 409)
                if row["status"] in {"uncertain", "creating"} and command.action != "create":
                    raise IntegrationError("external_reconciliation_required", 409)
                state, target = (
                    {"create": "creating", "merge": "merged", "discard": "discarded"}[
                        command.action
                    ],
                    command.target_subject_id,
                )
                if command.action == "merge":
                    if target not in {item["id"] for item in self.candidates_on(db, user, row)}:
                        raise IntegrationError("candidate_unavailable", 404)
                    db.execute(
                        "insert into public.merge_operations(tenant_id,lead_id,target_subject_id,actor_id,reason) values(%s,%s,%s,%s,%s)",
                        (user.tenant_id, id, target, user.user_id, command.reason),
                    )
                if command.action == "create" and not self.provider.capabilities().create_lead:
                    raise IntegrationError("lead_creation_capability_missing", 422)
            updated = db.execute(
                "update public.lead_intake set status=%s,target_subject_id=%s,reason=%s,version=version+1,updated_at=now() where tenant_id=%s and id=%s returning *",
                (state, target, command.reason, user.tenant_id, id),
            ).fetchone()
            assert updated
            self.audit(db, user, updated, f"lead.{command.action}", command.reason)
        if command.action != "create":
            return dict(updated)
        try:
            result = self.provider.create_lead(
                {key: row[key] for key in ["name", "email", "phone"]},
                f"ares-lead:{user.tenant_id}:{id}",
            )
        except Exception:
            with self.db() as db:
                db.execute(
                    "update public.lead_intake set status='uncertain',updated_at=now() where tenant_id=%s and id=%s",
                    (user.tenant_id, id),
                )
            raise IntegrationError("lead_write_uncertain_retry_same_intent", 503) from None
        with self.db() as db:
            subject = uuid4()
            db.execute(
                "insert into public.subjects(id,tenant_id,subject_type,display_name,source_authority,external_ref) values(%s,%s,'person',%s,'external',%s)",
                (
                    subject,
                    user.tenant_id,
                    row["name"],
                    Jsonb(
                        {
                            "provider": "http_fake",
                            "id": result.external_id,
                            "email": row["email"],
                            "phone": row["phone"],
                        }
                    ),
                ),
            )
            final = db.execute(
                "update public.lead_intake set status='created',external_id=%s,target_subject_id=%s,version=version+1,updated_at=now() where tenant_id=%s and id=%s returning *",
                (result.external_id, subject, user.tenant_id, id),
            ).fetchone()
            assert final
            self.audit(db, user, final, "lead.created", command.reason)
            return dict(final)
