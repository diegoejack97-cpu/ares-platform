"""Private text storage and hybrid retrieval, with authority checked before scoring."""

# ruff: noqa: E501
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

import psycopg
from openai import OpenAI
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.ai.quotas import QuotaGuard
from ares.ai.usage import UsageObservation, record_usage_on
from ares.auth.models import AuthenticatedUser
from ares.intelligence.context_builder import (
    ContextBuilder,
    ContextUnavailable,
    encode,
    fingerprint,
)
from ares.knowledge.models import PURPOSES, DocumentUpload, MemoryConfig
from ares.knowledge.text import chunks, digest, safe_text

EMBED_MODEL = "text-embedding-3-small"
EMBED_VERSION = "openai-1536-2026-10-09"
PRICE = Decimal("0.02") / 1_000_000


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]: ...


class OpenAIEmbedder:
    def __init__(self, key: str):
        self.client = OpenAI(api_key=key, timeout=15, max_retries=0)

    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        response = self.client.embeddings.create(model=EMBED_MODEL, input=texts, dimensions=1536)
        return [
            item.embedding for item in sorted(response.data, key=lambda item: item.index)
        ], response.usage.total_tokens


def vector(value: list[float]) -> str:
    import math

    if len(value) != 1536 or not all(math.isfinite(v) for v in value):
        raise ContextUnavailable("embedding_shape_invalid", 422)
    return "[" + ",".join(str(v) for v in value) + "]"


class KnowledgeService:
    def __init__(self, url: str, key: str = "", embedder: Embedder | None = None):
        self.url = url
        self.embedder = embedder or (OpenAIEmbedder(key) if key else None)

    @staticmethod
    def authority(db: psycopg.Connection[Any], user: AuthenticatedUser, admin: bool = False) -> str:
        role = ContextBuilder.authorize(db, user)
        if admin and role != "admin":
            raise ContextUnavailable("knowledge_admin_required", 403)
        return role

    @staticmethod
    def audit(
        db: psycopg.Connection[Any],
        user: AuthenticatedUser,
        operation: str,
        reason: str,
        document: UUID | None = None,
        metadata: Any = None,
    ) -> None:
        db.execute(
            "insert into public.knowledge_audit(id,tenant_id,actor_id,document_id,operation,reason,metadata) values(%s,%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                user.tenant_id,
                user.user_id,
                document,
                operation,
                reason,
                Jsonb(metadata or {}),
            ),
        )

    def configuration(self, user: AuthenticatedUser) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role = self.authority(db, user)
            row = db.execute(
                "select * from public.knowledge_settings where tenant_id=%s", (user.tenant_id,)
            ).fetchone()
            limits = db.execute(
                "select memory_storage_bytes,embedding_daily_budget_brl from public.tenant_quotas where tenant_id=%s",
                (user.tenant_id,),
            ).fetchone()
            return {
                "configuration": row
                or {
                    "version": 0,
                    "enabled": False,
                    "external_consent": False,
                    "outcomes_enabled": False,
                    "episodes_enabled": False,
                    "observation_hours": 48,
                    "retention_days": 90,
                },
                "can_configure": role == "admin",
                "limits": limits,
                "formats": ["txt", "md"],
                "max_file_bytes": 262144,
                "processing": "Texto e perguntas enviados à OpenAI somente com consentimento. Sem consentimento: busca textual local.",
                "embedding_model": EMBED_MODEL,
                "embedding_dimensions": 1536,
            }

    def configure(self, user: AuthenticatedUser, command: MemoryConfig) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            self.authority(db, user, True)
            db.execute(
                "select pg_advisory_xact_lock(hashtext(%s))", (str(user.tenant_id) + ":knowledge",)
            )
            row = db.execute(
                "select * from public.knowledge_settings where tenant_id=%s for update",
                (user.tenant_id,),
            ).fetchone()
            if command.expected_version != (row["version"] if row else 0):
                raise ContextUnavailable("knowledge_configuration_stale")
            db.execute(
                "insert into public.knowledge_settings(tenant_id,version,enabled,external_consent,outcomes_enabled,episodes_enabled,observation_hours,retention_days,updated_by) values(%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(tenant_id) do update set version=excluded.version,enabled=excluded.enabled,external_consent=excluded.external_consent,outcomes_enabled=excluded.outcomes_enabled,episodes_enabled=excluded.episodes_enabled,observation_hours=excluded.observation_hours,retention_days=excluded.retention_days,updated_by=excluded.updated_by,updated_at=now()",
                (
                    user.tenant_id,
                    command.expected_version + 1,
                    command.enabled,
                    command.external_consent,
                    command.outcomes_enabled,
                    command.episodes_enabled,
                    command.observation_hours,
                    command.retention_days,
                    user.user_id,
                ),
            )
            db.execute("delete from public.knowledge_reads where tenant_id=%s", (user.tenant_id,))
            self.audit(
                db, user, "configure", command.reason, metadata=command.model_dump(mode="json")
            )
            db.execute(
                "update public.knowledge_versions set expires_at=least(expires_at,created_at+(%s*interval '1 day')) where tenant_id=%s",
                (command.retention_days, user.tenant_id),
            )
        return self.configuration(user)

    def upload(self, user: AuthenticatedUser, command: DocumentUpload) -> dict[str, Any]:
        content = safe_text(command.content)
        size = len(content.encode())
        parts = chunks(content)
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            self.authority(db, user, True)
            db.execute(
                "select pg_advisory_xact_lock(hashtext(%s))", (str(user.tenant_id) + ":knowledge",)
            )
            quota = db.execute(
                "select memory_storage_bytes from public.tenant_quotas where tenant_id=%s for update",
                (user.tenant_id,),
            ).fetchone()
            config = db.execute(
                "select * from public.knowledge_settings where tenant_id=%s", (user.tenant_id,)
            ).fetchone()
            if not config or not config["enabled"]:
                raise ContextUnavailable("knowledge_disabled", 403)
            if "seller" in command.allowed_roles and command.owner_user_id is None:
                raise ContextUnavailable("knowledge_seller_scope_required", 422)
            if (
                command.owner_user_id
                and not db.execute(
                    "select 1 from public.memberships where tenant_id=%s and user_id=%s and active",
                    (user.tenant_id, command.owner_user_id),
                ).fetchone()
            ):
                raise ContextUnavailable("knowledge_owner_invalid", 422)
            old = (
                db.execute(
                    "select * from public.knowledge_documents where tenant_id=%s and id=%s for update",
                    (user.tenant_id, command.document_id),
                ).fetchone()
                if command.document_id
                else None
            )
            if command.document_id and (not old or old["deleted"]):
                raise ContextUnavailable("knowledge_document_missing", 404)
            if command.expected_version != (old["current_version"] if old else 0):
                raise ContextUnavailable("knowledge_document_stale")
            current = (
                db.execute(
                    "select * from public.knowledge_versions where tenant_id=%s and document_id=%s and version=%s",
                    (user.tenant_id, old["id"], old["current_version"]),
                ).fetchone()
                if old
                else None
            )
            if (
                current
                and old
                and current["content_hash"] == digest(content)
                and old["allowed_roles"] == command.allowed_roles
                and old["purposes"] == command.purposes
                and old["owner_user_id"] == command.owner_user_id
                and old["title"] == command.title
                and old["source_label"] == command.source_label
                and old["classification"] == command.classification
            ):
                return {
                    "document_id": old["id"],
                    "version": old["current_version"],
                    "status": current["status"],
                    "unchanged": True,
                }
            used_row = db.execute(
                "select coalesce(sum(size_bytes),0) n from public.knowledge_versions where tenant_id=%s and original_text is not null",
                (user.tenant_id,),
            ).fetchone()
            used = used_row["n"] if used_row else 0
            if (
                not quota
                or used
                - (current["size_bytes"] if current and current["original_text"] else 0)
                + size
                > quota["memory_storage_bytes"]
            ):
                raise ContextUnavailable("knowledge_storage_exceeded", 429)
            document = old["id"] if old else uuid4()
            revision = (old["current_version"] if old else 0) + 1
            reusable = (
                db.execute(
                    "select ordinal,embedding::text embedding,embedding_model,embedding_version from public.knowledge_chunks where tenant_id=%s and version_id=%s order by ordinal",
                    (user.tenant_id, current["id"]),
                ).fetchall()
                if current and current["content_hash"] == digest(content)
                else []
            )
            if old:
                self.purge_document_on(db, user.tenant_id, document, "superseded")
                db.execute(
                    "update public.knowledge_documents set title=%s,source_label=%s,classification=%s,allowed_roles=%s,owner_user_id=%s,purposes=%s,current_version=%s where tenant_id=%s and id=%s",
                    (
                        command.title,
                        command.source_label,
                        command.classification,
                        command.allowed_roles,
                        command.owner_user_id,
                        command.purposes,
                        revision,
                        user.tenant_id,
                        document,
                    ),
                )
            else:
                db.execute(
                    "insert into public.knowledge_documents(id,tenant_id,title,source_label,classification,allowed_roles,owner_user_id,purposes,created_by) values(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        document,
                        user.tenant_id,
                        command.title,
                        command.source_label,
                        command.classification,
                        command.allowed_roles,
                        command.owner_user_id,
                        command.purposes,
                        user.user_id,
                    ),
                )
            version_id = uuid4()
            expires = datetime.now(UTC) + timedelta(
                days=min(command.validity_days, config["retention_days"])
            )
            db.execute(
                "insert into public.knowledge_versions(id,tenant_id,document_id,version,content_hash,original_text,size_bytes,expires_at,status) values(%s,%s,%s,%s,%s,%s,%s,%s,'queued')",
                (
                    version_id,
                    user.tenant_id,
                    document,
                    revision,
                    digest(content),
                    content,
                    size,
                    expires,
                ),
            )
            for i, part in enumerate(parts):
                db.execute(
                    "insert into public.knowledge_chunks(id,tenant_id,version_id,ordinal,content,content_hash) values(%s,%s,%s,%s,%s,%s)",
                    (uuid4(), user.tenant_id, version_id, i, part, digest(part)),
                )
                if reusable and len(reusable) == len(parts):
                    reuse = reusable[i]
                    db.execute(
                        "update public.knowledge_chunks set embedding=%s::extensions.vector,embedding_model=%s,embedding_version=%s where tenant_id=%s and version_id=%s and ordinal=%s",
                        (
                            reuse["embedding"],
                            reuse["embedding_model"],
                            reuse["embedding_version"],
                            user.tenant_id,
                            version_id,
                            i,
                        ),
                    )
            if reusable and len(reusable) == len(parts):
                db.execute(
                    "update public.knowledge_versions set status=%s where tenant_id=%s and id=%s",
                    (
                        "ready"
                        if all(r["embedding"] is not None for r in reusable)
                        else "lexical_only",
                        user.tenant_id,
                        version_id,
                    ),
                )
            db.execute(
                "insert into public.jobs(tenant_id,kind,payload,correlation_id) values(%s,'memory.index',%s,%s)",
                (
                    user.tenant_id,
                    Jsonb({"version_id": str(version_id), "actor_id": str(user.user_id)}),
                    uuid4(),
                ),
            )
            self.audit(
                db,
                user,
                "upload",
                command.reason,
                document,
                {"version": revision, "hash": digest(content), "verified_source": True},
            )
            return {
                "document_id": document,
                "version": revision,
                "status": "queued",
                "unchanged": False,
            }

    @staticmethod
    def purge_document_on(
        db: psycopg.Connection[Any], tenant: UUID, document: UUID, status: str
    ) -> None:
        # No content or vectors retained in the audit trail. Invalidate all receipt caches.
        db.execute(
            "delete from public.knowledge_chunks where tenant_id=%s and version_id in(select id from public.knowledge_versions where tenant_id=%s and document_id=%s)",
            (tenant, tenant, document),
        )
        db.execute(
            "update public.knowledge_versions set original_text=null,status=%s where tenant_id=%s and document_id=%s",
            (status, tenant, document),
        )
        db.execute("delete from public.knowledge_reads where tenant_id=%s", (tenant,))
        # Assistant quotations are derived data too; deletion also redacts persisted quotations.
        db.execute(
            "update public.messages set assistant_text='Documento removido ou substituído. Faça uma nova consulta.', context_json=context_json-'memory' where tenant_id=%s and context_json->'memory'->'document_ids' ? %s",
            (tenant, str(document)),
        )

    def remove(self, user: AuthenticatedUser, document: UUID, reason: str) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            self.authority(db, user, True)
            row = db.execute(
                "select id from public.knowledge_documents where tenant_id=%s and id=%s for update",
                (user.tenant_id, document),
            ).fetchone()
            if not row:
                raise ContextUnavailable("knowledge_document_missing", 404)
            self.purge_document_on(db, user.tenant_id, document, "deleted")
            db.execute(
                "update public.knowledge_documents set deleted=true where tenant_id=%s and id=%s",
                (user.tenant_id, document),
            )
            self.audit(db, user, "delete", reason, document)
        return {"deleted": True}

    def expire(self) -> None:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            expired = db.execute(
                "select distinct tenant_id,document_id from public.knowledge_versions where expires_at<=now() and original_text is not null limit 50"
            ).fetchall()
            for row in expired:
                self.purge_document_on(db, row["tenant_id"], row["document_id"], "deleted")
            db.execute("delete from public.knowledge_reads where valid_until<=now()")

    def documents(self, user: AuthenticatedUser) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role = self.authority(db, user)
            rows = db.execute(
                "select d.*,v.status,v.expires_at,v.size_bytes,v.error_code from public.knowledge_documents d join public.knowledge_versions v on v.tenant_id=d.tenant_id and v.document_id=d.id and v.version=d.current_version where d.tenant_id=%s and not d.deleted and %s=any(d.allowed_roles) and (d.owner_user_id is null or d.owner_user_id=%s or %s in ('admin','manager','auditor')) order by d.created_at desc limit 100",
                (user.tenant_id, role, user.user_id, role),
            ).fetchall()
            return {"items": rows}

    def embed(
        self, user: AuthenticatedUser, texts: list[str], context: UUID, *, indexing: bool
    ) -> list[list[float]] | None:
        if not self.embedder:
            return None
        run = uuid4()
        usage = UsageObservation(status="not_called")
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            self.authority(db, user, indexing)
            config = db.execute(
                "select * from public.knowledge_settings where tenant_id=%s", (user.tenant_id,)
            ).fetchone()
            if not config or not config["enabled"] or not config["external_consent"]:
                return None
            quota = db.execute(
                "select * from public.tenant_quotas where tenant_id=%s for update",
                (user.tenant_id,),
            ).fetchone()
            if not quota:
                raise ContextUnavailable("knowledge_quota_missing", 403)
            estimate = sum(len(t.encode()) for t in texts) * PRICE
            if indexing:
                consumed_row = db.execute(
                    "select coalesce(sum(coalesce(measured_usd,reserved_usd)),0) n from public.knowledge_embedding_budget where tenant_id=%s and created_at>=date_trunc('day',now())",
                    (user.tenant_id,),
                ).fetchone()
                consumed = consumed_row["n"] if consumed_row else Decimal(0)
                if (
                    not quota
                    or (consumed + estimate) * quota["usd_brl_rate"]
                    > quota["embedding_daily_budget_brl"]
                ):
                    raise ContextUnavailable("embedding_budget_exceeded", 429)
            db.execute(
                "insert into public.context_snapshots(id,tenant_id,snapshot_version,opportunity_state,content_hash,source,facts_json,citations_json) values(%s,%s,1,'detected',%s,'ares',%s,'[]') on conflict(id) do nothing",
                (
                    context,
                    user.tenant_id,
                    fingerprint(texts),
                    Jsonb({"purpose": "embedding", "content_hash": fingerprint(texts)}),
                ),
            )
            db.execute(
                "insert into public.agent_runs(id,tenant_id,context_ref,correlation_id,agent_name,agent_version,definition_hash,prompt_hash,input_schema_version,output_schema_version,generation_mode,status,checkpoint) values(%s,%s,%s,%s,'memory-indexer',%s,%s,%s,'embedding-input.v1','embedding-output.v1','openai_embeddings','running','dispatched')",
                (
                    run,
                    user.tenant_id,
                    context,
                    uuid4(),
                    EMBED_VERSION,
                    fingerprint([EMBED_MODEL, EMBED_VERSION]),
                    fingerprint(texts),
                ),
            )
            if not QuotaGuard(self.url).reserve_on(db, user.tenant_id, run, estimate).allowed:
                db.execute(
                    "update public.agent_runs set status='failed',error_code='memory_budget_exceeded',finished_at=now() where tenant_id=%s and id=%s",
                    (user.tenant_id, run),
                )
                db.commit()
                raise ContextUnavailable("memory_budget_exceeded", 429)
            if indexing:
                db.execute(
                    "insert into public.knowledge_embedding_budget(tenant_id,run_id,reserved_usd) values(%s,%s,%s)",
                    (user.tenant_id, run, estimate),
                )
        try:
            usage = UsageObservation(model_id=EMBED_MODEL)
            vectors, tokens = self.embedder.embed(texts)
            if type(tokens) is not int or tokens < 0 or len(vectors) != len(texts):
                raise ContextUnavailable("embedding_response_invalid")
            usage = UsageObservation(
                "observed", EMBED_MODEL, tokens, 0, 0, Decimal(tokens) * PRICE, EMBED_VERSION
            )
            for item in vectors:
                vector(item)
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                self.authority(db, user, indexing)
                fresh = db.execute(
                    "select * from public.knowledge_settings where tenant_id=%s", (user.tenant_id,)
                ).fetchone()
                if (
                    not fresh
                    or not fresh["enabled"]
                    or not fresh["external_consent"]
                    or fresh["version"] != config["version"]
                ):
                    raise ContextUnavailable("knowledge_consent_changed")
            return vectors
        finally:
            with psycopg.connect(self.url) as db:
                record_usage_on(db, user.tenant_id, run, usage)
                if indexing and usage.cost_usd is not None:
                    db.execute(
                        "update public.knowledge_embedding_budget set measured_usd=%s where tenant_id=%s and run_id=%s",
                        (usage.cost_usd, user.tenant_id, run),
                    )
                db.execute(
                    "update public.agent_runs set status=%s,finished_at=now(),checkpoint='completed' where tenant_id=%s and id=%s",
                    ("succeeded" if usage.status == "observed" else "failed", user.tenant_id, run),
                )

    def index(self, tenant: UUID, payload: dict[str, Any]) -> None:
        user = AuthenticatedUser(tenant_id=tenant, user_id=UUID(payload["actor_id"]), role="admin")
        version_id = UUID(payload["version_id"])
        try:
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                self.authority(db, user, True)
                row = db.execute(
                    "select v.* from public.knowledge_versions v join public.knowledge_documents d on d.tenant_id=v.tenant_id and d.id=v.document_id where v.tenant_id=%s and v.id=%s and v.version=d.current_version and not d.deleted and v.expires_at>now() for update of v",
                    (tenant, version_id),
                ).fetchone()
                if not row or row["status"] not in ("queued", "indexing"):
                    return
                if row["status"] == "indexing" or payload.get("recovered"):
                    raise ContextUnavailable("embedding_outcome_unknown")
                parts = db.execute(
                    "select * from public.knowledge_chunks where tenant_id=%s and version_id=%s order by ordinal",
                    (tenant, version_id),
                ).fetchall()
                cached = {}
                for part in parts:
                    reuse = db.execute(
                        "select c.embedding::text embedding from public.knowledge_chunks c join public.knowledge_versions v on v.tenant_id=c.tenant_id and v.id=c.version_id join public.knowledge_documents d on d.tenant_id=v.tenant_id and d.id=v.document_id where c.tenant_id=%s and c.content_hash=%s and c.embedding_model=%s and c.embedding_version=%s and c.embedding is not null and v.status='ready' and v.expires_at>now() and v.version=d.current_version and not d.deleted limit 1",
                        (tenant, part["content_hash"], EMBED_MODEL, EMBED_VERSION),
                    ).fetchone()
                    if reuse:
                        cached[str(part["id"])] = reuse["embedding"]
                db.execute(
                    "update public.knowledge_versions set status='indexing' where tenant_id=%s and id=%s",
                    (tenant, version_id),
                )
            missing = [p for p in parts if str(p["id"]) not in cached]
            vectors = (
                self.embed(user, [p["content"] for p in missing], version_id, indexing=True)
                if missing
                else []
            )
            with psycopg.connect(self.url, row_factory=dict_row) as db:
                self.authority(db, user, True)
                active = db.execute(
                    "select v.id from public.knowledge_versions v join public.knowledge_documents d on d.tenant_id=v.tenant_id and d.id=v.document_id where v.tenant_id=%s and v.id=%s and v.version=d.current_version and not d.deleted and v.status='indexing' and v.expires_at>now() for update of v",
                    (tenant, version_id),
                ).fetchone()
                if not active:
                    raise ContextUnavailable("knowledge_version_stale")
                if vectors:
                    for part, embedding in zip(missing, vectors, strict=True):
                        db.execute(
                            "update public.knowledge_chunks set embedding=%s::extensions.vector,embedding_model=%s,embedding_version=%s where tenant_id=%s and id=%s",
                            (vector(embedding), EMBED_MODEL, EMBED_VERSION, tenant, part["id"]),
                        )
                for part in parts:
                    if str(part["id"]) in cached:
                        db.execute(
                            "update public.knowledge_chunks set embedding=%s::extensions.vector,embedding_model=%s,embedding_version=%s where tenant_id=%s and id=%s",
                            (
                                cached[str(part["id"])],
                                EMBED_MODEL,
                                EMBED_VERSION,
                                tenant,
                                part["id"],
                            ),
                        )
                db.execute(
                    "update public.knowledge_versions set status=%s where tenant_id=%s and id=%s",
                    ("ready" if vectors or not missing else "lexical_only", tenant, version_id),
                )
        except Exception as error:
            with psycopg.connect(self.url) as db:
                db.execute(
                    "update public.knowledge_versions set status='failed',error_code=%s where tenant_id=%s and id=%s and status in ('queued','indexing')",
                    (getattr(error, "code", "knowledge_index_failed"), tenant, version_id),
                )

    def retrieve(self, user: AuthenticatedUser, question: str, purpose: str) -> dict[str, Any]:
        if purpose not in PURPOSES:
            raise ContextUnavailable("knowledge_purpose_invalid", 422)
        if not 3 <= len(question) <= 1200:
            raise ContextUnavailable("knowledge_question_invalid", 422)
        safe_text(question)
        receipt = uuid4()
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role = self.authority(db, user)
            config = db.execute(
                "select * from public.knowledge_settings where tenant_id=%s", (user.tenant_id,)
            ).fetchone()
            if not config or not config["enabled"]:
                return {
                    "context_ref": str(receipt),
                    "hits": [],
                    "mode": "disabled",
                    "document_ids": [],
                }
            if not db.execute(
                "select 1 from public.knowledge_documents d join public.knowledge_versions v on v.tenant_id=d.tenant_id and v.document_id=d.id and v.version=d.current_version where d.tenant_id=%s and not d.deleted and v.status in ('ready','lexical_only') and v.expires_at>now() and %s=any(d.allowed_roles) and %s=any(d.purposes) and (d.owner_user_id is null or d.owner_user_id=%s or %s in ('admin','manager','auditor')) limit 1",
                (user.tenant_id, role, purpose, user.user_id, role),
            ).fetchone():
                return {
                    "context_ref": str(receipt),
                    "hits": [],
                    "mode": "lexical",
                    "document_ids": [],
                }
        embedding = self.embed(user, [question], receipt, indexing=False)
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role = self.authority(db, user)
            config = db.execute(
                "select * from public.knowledge_settings where tenant_id=%s", (user.tenant_id,)
            ).fetchone()
            if not config or not config["enabled"]:
                raise ContextUnavailable("knowledge_disabled", 403)
            query_vector = (
                vector(embedding[0]) if embedding and config["external_consent"] else None
            )
            # MATERIALIZED authorized candidates prevent ANN/global ranking leaking a different tenant.
            rows = db.execute(
                """with allowed as materialized (
             select c.*,d.id document_id,d.title,d.source_label,v.version,v.id version_ref
             from public.knowledge_chunks c join public.knowledge_versions v on v.tenant_id=c.tenant_id and v.id=c.version_id
             join public.knowledge_documents d on d.tenant_id=v.tenant_id and d.id=v.document_id
             where c.tenant_id=%s and not d.deleted and d.current_version=v.version and v.expires_at>clock_timestamp()
              and v.status in ('ready','lexical_only') and %s=any(d.allowed_roles) and %s=any(d.purposes)
              and (d.owner_user_id is null or d.owner_user_id=%s or %s in ('admin','manager','auditor'))
            ), terms as (select to_tsquery('portuguese',string_agg(quote_literal(term),' | ')) q from unnest(tsvector_to_array(to_tsvector('portuguese',%s))) term),
            keyword as (select id,row_number() over(order by ts_rank_cd(search_vector,terms.q) desc,id) r from allowed,terms where search_vector@@terms.q order by r limit 20),
            semantic as (select id,row_number() over(order by embedding OPERATOR(extensions.<=>) %s::extensions.vector,id) r from allowed where embedding is not null and embedding_model=%s and embedding_version=%s and %s::text is not null and embedding OPERATOR(extensions.<=>) %s::extensions.vector < 0.65 order by r limit 20)
            select a.id chunk_id,a.document_id,a.title,a.source_label,a.version,a.version_ref,a.content,
             coalesce(1.0/(60+k.r),0)+coalesce(1.0/(60+s.r),0) score from allowed a left join keyword k on k.id=a.id left join semantic s on s.id=a.id where k.id is not null or s.id is not null order by score desc,a.id limit 5""",
                (
                    user.tenant_id,
                    role,
                    purpose,
                    user.user_id,
                    role,
                    question,
                    query_vector,
                    EMBED_MODEL,
                    EMBED_VERSION,
                    query_vector,
                    query_vector,
                ),
            ).fetchall()
            hits = []
            remaining = 2000
            for row in rows:
                # Do not manufacture a quotation by slicing through a UTF-8 sequence.
                quote = (
                    row["content"].encode()[: min(800, remaining)].decode("utf-8", errors="ignore")
                )
                if not quote:
                    break
                hit = {
                    **{
                        k: str(v) if isinstance(v, UUID) else v
                        for k, v in row.items()
                        if k not in ("content", "score")
                    },
                    "quote": quote,
                }
                cost = len(encode(hit).encode())
                if cost > remaining:
                    break
                hits.append(hit)
                remaining -= cost
                if remaining <= 0:
                    break
            refs = [
                {
                    "document_id": h["document_id"],
                    "version_ref": h["version_ref"],
                    "chunk_id": h["chunk_id"],
                    "version": h["version"],
                }
                for h in hits
            ]
            db.execute(
                "insert into public.knowledge_reads(id,tenant_id,actor_id,purpose,references_json,content_hash,valid_until) values(%s,%s,%s,%s,%s,%s,now()+interval '60 seconds')",
                (receipt, user.tenant_id, user.user_id, purpose, Jsonb(refs), fingerprint(hits)),
            )
            return {
                "context_ref": str(receipt),
                "content_hash": fingerprint(hits),
                "hits": hits,
                "mode": "hybrid" if query_vector else "lexical",
                "document_ids": list(dict.fromkeys(h["document_id"] for h in hits)),
            }

    def validate_read(self, user: AuthenticatedUser, receipt: UUID) -> None:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role = self.authority(db, user)
            row = db.execute(
                "select * from public.knowledge_reads where tenant_id=%s and actor_id=%s and id=%s and valid_until>now()",
                (user.tenant_id, user.user_id, receipt),
            ).fetchone()
            config = db.execute(
                "select enabled from public.knowledge_settings where tenant_id=%s",
                (user.tenant_id,),
            ).fetchone()
            if not row or not config or not config["enabled"]:
                raise ContextUnavailable("knowledge_receipt_stale")
            for ref in row["references_json"]:
                if not db.execute(
                    "select 1 from public.knowledge_documents d join public.knowledge_versions v on v.tenant_id=d.tenant_id and v.document_id=d.id join public.knowledge_chunks c on c.tenant_id=v.tenant_id and c.version_id=v.id where d.tenant_id=%s and d.id=%s and not d.deleted and d.current_version=%s and v.id=%s and v.expires_at>now() and v.status in ('ready','lexical_only') and c.id=%s and %s=any(d.allowed_roles) and %s=any(d.purposes) and (d.owner_user_id is null or d.owner_user_id=%s or %s in ('admin','manager','auditor'))",
                    (
                        user.tenant_id,
                        ref["document_id"],
                        ref["version"],
                        ref["version_ref"],
                        ref["chunk_id"],
                        role,
                        row["purpose"],
                        user.user_id,
                        role,
                    ),
                ).fetchone():
                    raise ContextUnavailable("knowledge_access_revoked")

    def validate_sources(self, user: AuthenticatedUser, memory: dict[str, Any]) -> None:
        """History rechecks live permissions; it never trusts a cached role or old quote."""
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            role = self.authority(db, user)
            config = db.execute(
                "select enabled from public.knowledge_settings where tenant_id=%s",
                (user.tenant_id,),
            ).fetchone()
            if not config or not config["enabled"]:
                raise ContextUnavailable("knowledge_disabled", 403)
            for hit in memory.get("hits", []):
                if not db.execute(
                    "select 1 from public.knowledge_documents d join public.knowledge_versions v on v.tenant_id=d.tenant_id and v.document_id=d.id join public.knowledge_chunks c on c.tenant_id=v.tenant_id and c.version_id=v.id where d.tenant_id=%s and d.id=%s and not d.deleted and d.current_version=%s and v.id=%s and v.expires_at>now() and v.status in ('ready','lexical_only') and c.id=%s and %s=any(d.allowed_roles) and 'chat'=any(d.purposes) and (d.owner_user_id is null or d.owner_user_id=%s or %s in ('admin','manager','auditor'))",
                    (
                        user.tenant_id,
                        hit["document_id"],
                        hit["version"],
                        hit["version_ref"],
                        hit["chunk_id"],
                        role,
                        user.user_id,
                        role,
                    ),
                ).fetchone():
                    raise ContextUnavailable("knowledge_access_revoked")
