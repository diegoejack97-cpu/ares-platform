"""Human-confirmed commands; deliberately separate from the M3 agent policy."""

import json
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from ares.auth.models import AuthenticatedUser
from ares.connectors.http_fake_crm import CRMProviderRequestError
from ares.decision.execution_guard import ExecutionBlocked, execution_contract
from ares.integrations.models import StageCommand, digest, normalize
from ares.integrations.service import IntegrationError, IntegrationService


class PipelineService(IntegrationService):
    def move(self, user: AuthenticatedUser, deal_id: UUID, command: StageCommand) -> dict[str, Any]:
        self.manager(user)
        if not command.confirmed:
            raise IntegrationError("explicit_confirmation_required", 422)
        # Session lock is held across I/O, but no SQL transaction is held across network calls.
        with self.db() as guard:
            guard.autocommit = True
            lock_name = f"pipeline:{self.tenant_id}"
            acquired = guard.execute(
                "select pg_try_advisory_lock(hashtext(%s)) as ok", (lock_name,)
            ).fetchone()
            if not acquired or not acquired["ok"]:
                raise IntegrationError("write_in_progress")
            try:
                with execution_contract(self.database_url, self.tenant_id):
                    return self._move_locked(user, deal_id, command)
            except ExecutionBlocked as error:
                raise IntegrationError(error.code, 403) from error
            finally:
                guard.execute("select pg_advisory_unlock(hashtext(%s))", (lock_name,))

    def _move_locked(
        self,
        user: AuthenticatedUser,
        deal_id: UUID,
        command: StageCommand,
    ) -> dict[str, Any]:
        request = {
            **command.model_dump(mode="json"),
            "deal_id": str(deal_id),
            "actor_id": str(user.user_id),
        }
        fingerprint = digest(request)
        intent: dict[str, Any] | None
        with self.db() as db:
            conn = self.connection(db)
            if not conn or conn["status"] == "revoked" or not conn["mapping_version"]:
                raise IntegrationError("active_mapping_required", 422)
            if not conn["capabilities"].get("update_stage"):
                raise IntegrationError("stage_write_capability_missing", 422)
            prior = db.execute(
                "select * from public.external_write_dedup "
                "where tenant_id=%s and idempotency_key=%s",
                (self.tenant_id, command.idempotency_key),
            ).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise IntegrationError("idempotency_key_reused_with_different_payload")
                if prior["status"] == "succeeded":
                    return {**prior["response_json"], "duplicate": True}
                if prior["status"] in {"conflict", "failed"}:
                    raise IntegrationError(prior["error_code"], 409, str(prior["correlation_id"]))
                intent = prior
                before = prior["state_before"]
                # Replay the exact approved external mapping, even after a mapping edit.
                external_stage = prior["request_json"]["external_stage"]
                raw_id = before["external_ref"]["id"]
            else:
                before_row = db.execute(
                    "select * from public.deals where tenant_id=%s and connection_id=%s and id=%s",
                    (self.tenant_id, conn["id"], deal_id),
                ).fetchone()
                if not before_row:
                    raise IntegrationError("deal_not_found", 404)
                if before_row["is_missing"]:
                    raise IntegrationError("deal_missing_in_source")
                if before_row["external_version"] != command.expected_version:
                    raise IntegrationError("source_version_conflict")
                mapping = self.mapping(db, conn)
                stage = next(
                    (s for s in mapping.stages if s.canonical_stage == command.stage), None
                )
                if stage is None:
                    raise IntegrationError("unmapped_target_stage", 422)
                external_stage = stage.external_stage
                if before_row["external_stage"] == external_stage:
                    raise IntegrationError("stage_unchanged", 422)
                before = json.loads(json.dumps(before_row, default=str))
                raw_id = before["external_ref"]["id"]
                policy_id, correlation_id, intent_id = uuid4(), uuid4(), uuid4()
                db.execute(
                    "insert into public.policy_decisions(id,tenant_id,policy_set,policy_version,"
                    "inputs_hash,verdict,rules_matched,obligations) "
                    "values(%s,%s,'m4_manual_pipeline',1,%s,'allow',%s,%s)",
                    (
                        policy_id,
                        self.tenant_id,
                        fingerprint,
                        Jsonb(
                            [
                                "manager_or_admin",
                                "explicit_human_confirmation",
                                "capability_checked",
                            ]
                        ),
                        Jsonb(["expected_version", "external_confirmation", "no_ai_attribution"]),
                    ),
                )
                intent = db.execute(
                    "insert into public.external_write_dedup(id,tenant_id,connection_id,deal_id,"
                    "idempotency_key,fingerprint,actor_id,correlation_id,policy_decision_id,status,"
                    "request_json,state_before) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s) "
                    "returning *",
                    (
                        intent_id,
                        self.tenant_id,
                        conn["id"],
                        deal_id,
                        command.idempotency_key,
                        fingerprint,
                        user.user_id,
                        correlation_id,
                        policy_id,
                        Jsonb({**request, "external_stage": external_stage}),
                        Jsonb(before),
                    ),
                ).fetchone()
                db.execute(
                    "insert into public.audit_log(tenant_id,actor_type,actor_id,action,"
                    "correlation_id,source,data) values(%s,'human',%s,'pipeline.approved',%s,"
                    "'ares:pipeline',%s)",
                    (
                        self.tenant_id,
                        user.user_id,
                        correlation_id,
                        Jsonb(
                            {
                                "intent_id": str(intent_id),
                                "policy_decision_id": str(policy_id),
                                "ares_intervention": False,
                                "attribution_level": "none",
                            }
                        ),
                    ),
                )
            assert intent is not None
        remote_accepted = False
        try:
            # The HTTP adapter accepts a correlation for every request in this human intent.
            if hasattr(self.provider, "correlation_id"):
                self.provider.correlation_id = str(intent["correlation_id"])
            result = self.provider.update_deal_stage(
                raw_id,
                external_stage,
                str(command.idempotency_key),
                command.expected_version,
            )
            remote_accepted = True
            reader = getattr(self.provider, "get_deal", None)
            if reader is None:
                raise IntegrationError("source_confirmation_unavailable", 503)
            confirmed = reader(raw_id)
            if (
                confirmed.id != raw_id
                or confirmed.stage != external_stage
                or confirmed.version <= command.expected_version
            ):
                raise IntegrationError("source_confirmation_diverged", 503)
            raw = confirmed.model_dump(mode="json")
            with self.db() as db:
                current = self.connection(db)
                if current is None:
                    raise IntegrationError("connection_unavailable", 503)
                db.execute(
                    "select id from public.connections where id=%s for update", (conn["id"],)
                )
                record = normalize(raw, self.mapping(db, current))
                self.persist_record(db, current, raw, record, None, intent["correlation_id"])
                response = {
                    "status": "succeeded",
                    "correlation_id": str(intent["correlation_id"]),
                    "external_id": result.external_id,
                    "duplicate": result.duplicate,
                    "ares_intervention": False,
                    "attribution_level": "none",
                    "confirmed_version": record["version"],
                }
                db.execute(
                    "update public.external_write_dedup set status='succeeded',state_after=%s,"
                    "response_json=%s,error_code=null,updated_at=now() "
                    "where tenant_id=%s and id=%s",
                    (Jsonb(raw), Jsonb(response), self.tenant_id, intent["id"]),
                )
                db.execute(
                    "insert into public.deal_stage_history(tenant_id,deal_id,write_id,from_stage,"
                    "to_stage,actor_id,correlation_id) values(%s,%s,%s,%s,%s,%s,%s) "
                    "on conflict(tenant_id,write_id) do nothing",
                    (
                        self.tenant_id,
                        deal_id,
                        intent["id"],
                        before["external_stage"],
                        external_stage,
                        user.user_id,
                        intent["correlation_id"],
                    ),
                )
                db.execute(
                    "insert into "
                    "public.audit_log(tenant_id,actor_type,actor_id,action,correlation_id,"
                    "source,data) values(%s,'human',%s,'pipeline.executed',%s,'crm',%s)",
                    (
                        self.tenant_id,
                        user.user_id,
                        intent["correlation_id"],
                        Jsonb({**response, "intent_id": str(intent["id"])}),
                    ),
                )
            return response
        except Exception as error:
            # After an accepted remote command, any local failure is uncertain, not a rejection.
            rejected = (
                not remote_accepted
                and isinstance(error, CRMProviderRequestError)
                and error.status_code
                in {
                    400,
                    401,
                    403,
                    404,
                    409,
                    422,
                }
            )
            status = (
                "conflict"
                if rejected and getattr(error, "status_code", None) == 409
                else ("failed" if rejected else "uncertain")
            )
            code = getattr(error, "code", "confirmation_uncertain")
            with self.db() as db:
                db.execute(
                    "update public.external_write_dedup set status=%s,error_code=%s,"
                    "updated_at=now() where tenant_id=%s and id=%s",
                    (status, code, self.tenant_id, intent["id"]),
                )
            raise IntegrationError(
                code, 409 if rejected else 503, str(intent["correlation_id"])
            ) from error
