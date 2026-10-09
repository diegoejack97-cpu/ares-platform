"""Tenant-scoped CRM mirror. External CRM remains the authority for the funnel."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.auth.models import AuthenticatedUser
from ares.connectors.provider import CRMProvider
from ares.integrations.models import (
    MappingCommand,
    SyncCommand,
    digest,
    normalize,
    suggested_mapping,
)


class IntegrationError(ValueError):
    def __init__(self, code: str, status: int = 409, correlation_id: str | None = None) -> None:
        super().__init__(code)
        self.code, self.status, self.correlation_id = code, status, correlation_id


class IntegrationService:
    def __init__(self, database_url: str, tenant_id: UUID, provider: CRMProvider) -> None:
        self.database_url, self.tenant_id, self.provider = database_url, tenant_id, provider

    def db(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def entitled(self, db: psycopg.Connection[dict[str, Any]]) -> None:
        if not db.execute(
            "select 1 from public.tenant_entitlements where tenant_id=%s "
            "and module='ares_connect' and status='active' "
            "and (expires_at is null or expires_at>now())",
            (self.tenant_id,),
        ).fetchone():
            raise IntegrationError("ares_connect_entitlement_required", 403)

    def manager(self, user: AuthenticatedUser) -> None:
        if user.tenant_id != self.tenant_id or user.role not in {"admin", "manager"}:
            raise IntegrationError("manager_required", 403)

    def connection(self, db: psycopg.Connection[dict[str, Any]]) -> dict[str, Any] | None:
        self.entitled(db)
        return db.execute(
            "select * from public.connections where tenant_id=%s and provider='fake-crm-http'",
            (self.tenant_id,),
        ).fetchone()

    def mapping(
        self, db: psycopg.Connection[dict[str, Any]], conn: dict[str, Any]
    ) -> MappingCommand:
        args = (self.tenant_id, conn["id"], conn["mapping_version"])
        fields = db.execute(
            "select canonical_field,provider_path,transformation,required "
            "from public.field_mappings "
            "where tenant_id=%s and connection_id=%s and mapping_version=%s "
            "order by canonical_field",
            args,
        ).fetchall()
        stages = db.execute(
            "select external_stage,canonical_stage,label,position from public.stage_mappings "
            "where tenant_id=%s and connection_id=%s and mapping_version=%s order by position",
            args,
        ).fetchall()
        return MappingCommand.model_validate(
            {"expected_version": conn["mapping_version"], "fields": fields, "stages": stages}
        )

    def get_mapping(self) -> dict[str, Any]:
        with self.db() as db:
            conn = self.connection(db)
            mapping = (
                self.mapping(db, conn).model_dump() if conn and conn["mapping_version"] else {}
            )
        return {
            "connection": conn,
            "mapping": {
                "version": mapping.pop("expected_version", 0),
                "fields": mapping.get("fields", []),
                "stages": mapping.get("stages", []),
            },
            "suggested": suggested_mapping(),
        }

    def save_mapping(self, user: AuthenticatedUser, command: MappingCommand) -> dict[str, Any]:
        self.manager(user)
        with self.db() as db:
            self.entitled(db)
        capabilities = self.provider.capabilities()
        if not capabilities.read_deals or not capabilities.describe_schema:
            raise IntegrationError("provider_mapping_capability_missing", 422)
        schema = self.provider.describe_schema()
        if any(
            field.provider_path not in schema.get("deal_fields", []) for field in command.fields
        ):
            raise IntegrationError("source_field_not_in_schema", 422)
        sample = self.provider.list_deals(limit=50)
        for record in sample.items:
            normalize(record.model_dump(mode="json"), command)
        with self.db() as db:
            self.entitled(db)
            db.execute(
                "select pg_advisory_xact_lock(hashtext(%s))", (f"pipeline:{self.tenant_id}",)
            )
            conn = self.connection(db)
            if conn is None:
                conn = db.execute(
                    "insert into public.connections(tenant_id,provider,capabilities) "
                    "values(%s,'fake-crm-http',%s) returning *",
                    (self.tenant_id, Jsonb(capabilities.model_dump())),
                ).fetchone()
            assert conn is not None
            db.execute("select id from public.connections where id=%s for update", (conn["id"],))
            if conn["status"] == "revoked":
                raise IntegrationError("connection_revoked", 403)
            if conn["mapping_version"] != command.expected_version:
                raise IntegrationError("mapping_version_conflict")
            if db.execute(
                "select 1 from public.jobs where tenant_id=%s and kind='integration.sync' "
                "and payload->>'connection_id'=%s and status in ('queued','running')",
                (self.tenant_id, str(conn["id"])),
            ).fetchone():
                raise IntegrationError("sync_in_progress")
            version = command.expected_version + 1
            db.execute(
                "insert into public.connection_schema_snapshots "
                "(tenant_id,connection_id,version,schema_json,actor_id) values(%s,%s,%s,%s,%s)",
                (self.tenant_id, conn["id"], version, Jsonb(schema), user.user_id),
            )
            for field in command.fields:
                db.execute(
                    "insert into public.field_mappings(tenant_id,connection_id,mapping_version,"
                    "canonical_field,provider_path,transformation,required) "
                    "values(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.tenant_id,
                        conn["id"],
                        version,
                        field.canonical_field,
                        field.provider_path,
                        field.transformation,
                        field.required,
                    ),
                )
            for stage in command.stages:
                db.execute(
                    "insert into public.stage_mappings(tenant_id,connection_id,mapping_version,"
                    "external_stage,canonical_stage,label,position) values(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.tenant_id,
                        conn["id"],
                        version,
                        stage.external_stage,
                        stage.canonical_stage,
                        stage.label,
                        stage.position,
                    ),
                )
            db.execute(
                "update public.connections set mapping_version=%s,capabilities=%s,"
                "status='configured',last_sync_at=null,updated_at=now() "
                "where tenant_id=%s and id=%s",
                (version, Jsonb(capabilities.model_dump()), self.tenant_id, conn["id"]),
            )
            # A changed mapping requires a full reconciliation, never reuses an old watermark.
            db.execute(
                "delete from public.sync_cursors where tenant_id=%s and connection_id=%s",
                (self.tenant_id, conn["id"]),
            )
        return self.get_mapping()

    def enqueue(self, user: AuthenticatedUser, command: SyncCommand) -> dict[str, Any]:
        self.manager(user)
        with self.db() as db:
            conn = self.connection(db)
            if not conn or not conn["mapping_version"] or conn["status"] == "revoked":
                raise IntegrationError("active_mapping_required", 422)
            db.execute("select id from public.connections where id=%s for update", (conn["id"],))
            active = db.execute(
                "select * from public.jobs where tenant_id=%s and kind='integration.sync' "
                "and payload->>'connection_id'=%s and status in ('queued','running')",
                (self.tenant_id, str(conn["id"])),
            ).fetchone()
            if active:
                return dict(active)
            checkpoint = db.execute(
                "select watermark from public.sync_cursors where tenant_id=%s and connection_id=%s",
                (self.tenant_id, conn["id"]),
            ).fetchone()
            since = command.since
            if command.mode == "incremental" and checkpoint and checkpoint["watermark"]:
                since = checkpoint["watermark"] - timedelta(minutes=5)
            payload = {
                "connection_id": str(conn["id"]),
                "mapping_version": conn["mapping_version"],
                "mode": command.mode,
                "since": since.isoformat() if since else None,
                "until": command.until.isoformat() if command.until else None,
                "cursor": None,
                "records": 0,
                "pages": 0,
                "actor_id": str(user.user_id),
            }
            row = db.execute(
                "insert into public.jobs(tenant_id,kind,payload,correlation_id) "
                "values(%s,'integration.sync',%s,%s) returning *",
                (self.tenant_id, Jsonb(payload), uuid4()),
            ).fetchone()
        assert row is not None
        return dict(row)

    def jobs(self) -> dict[str, Any]:
        with self.db() as db:
            self.entitled(db)
            rows = db.execute(
                "select * from public.jobs where tenant_id=%s "
                "and kind='integration.sync' order by created_at desc limit 30",
                (self.tenant_id,),
            ).fetchall()
        return {"items": rows}

    def retry(self, user: AuthenticatedUser, job_id: UUID) -> dict[str, Any]:
        self.manager(user)
        with self.db() as db:
            conn = self.connection(db)
            if not conn or conn["status"] == "revoked":
                raise IntegrationError("active_mapping_required", 422)
            db.execute("select id from public.connections where id=%s for update", (conn["id"],))
            if db.execute(
                "select 1 from public.jobs where tenant_id=%s and kind='integration.sync' "
                "and status in ('queued','running')",
                (self.tenant_id,),
            ).fetchone():
                raise IntegrationError("sync_in_progress")
            row = db.execute(
                "update public.jobs set "
                "status='queued',attempts=0,run_after=now(),finished_at=null,"
                "error_code=null,updated_at=now() where id=%s and tenant_id=%s "
                "and kind='integration.sync' and status in ('failed','dead_letter') returning *",
                (job_id, self.tenant_id),
            ).fetchone()
            if not row:
                raise IntegrationError("retryable_job_not_found", 404)
            if row["payload"]["mapping_version"] != conn["mapping_version"]:
                raise IntegrationError("mapping_changed_start_new_sync")
        return dict(row)

    def process_job(self, job: dict[str, Any]) -> None:
        payload = dict(job["payload"])
        with self.db() as db:
            conn = self.connection(db)
            if (
                not conn
                or str(conn["id"]) != payload["connection_id"]
                or conn["status"] == "revoked"
                or conn["mapping_version"] != payload["mapping_version"]
            ):
                raise IntegrationError("mapping_changed_start_new_sync")
            mapping = self.mapping(db, conn)
        since = datetime.fromisoformat(payload["since"]) if payload.get("since") else None
        page = self.provider.list_deals(cursor=payload.get("cursor"), limit=25, changed_after=since)
        records = [
            (item.model_dump(mode="json"), normalize(item.model_dump(mode="json"), mapping))
            for item in page.items
        ]
        until = datetime.fromisoformat(payload["until"]) if payload.get("until") else None
        with self.db() as db:
            self.entitled(db)
            current = db.execute(
                "select * from public.connections where tenant_id=%s and id=%s for update",
                (self.tenant_id, conn["id"]),
            ).fetchone()
            if (
                not current
                or current["status"] == "revoked"
                or current["mapping_version"] != payload["mapping_version"]
            ):
                raise IntegrationError("mapping_changed_start_new_sync")
            for raw, record in records:
                if until is None or record["changed_at"] <= until:
                    self.persist_record(db, conn, raw, record, job["id"], job["correlation_id"])
                    payload["records"] += 1
            payload.update(cursor=page.next_cursor, pages=payload["pages"] + 1)
            if page.watermark is not None:
                payload["watermark"] = page.watermark.isoformat()
            finished = page.next_cursor is None
            db.execute(
                "update public.jobs set payload=%s,status=%s,attempts=0,updated_at=now(),"
                "run_after=now(),lease_owner=null,lease_until=null,"
                "finished_at=case when %s then now() else null end where tenant_id=%s and id=%s",
                (
                    Jsonb(payload),
                    "succeeded" if finished else "queued",
                    finished,
                    self.tenant_id,
                    job["id"],
                ),
            )
            if finished:
                if payload["mode"] != "historical":
                    db.execute(
                        "insert into public.sync_cursors(tenant_id,connection_id,watermark,"
                        "last_completed_at) values(%s,%s,%s,now()) on conflict "
                        "(tenant_id,connection_id,entity_type) do update set "
                        "watermark=greatest(sync_cursors.watermark,excluded.watermark),"
                        "last_completed_at=now(),updated_at=now()",
                        (self.tenant_id, conn["id"], payload.get("watermark")),
                    )
                if payload["mode"] == "reconcile":
                    db.execute(
                        "update public.deals d set is_missing=true where d.tenant_id=%s "
                        "and d.connection_id=%s and exists(select 1 from public.external_records r "
                        "where r.tenant_id=d.tenant_id and r.deal_id=d.id "
                        "and r.last_seen_run is distinct from %s)",
                        (self.tenant_id, conn["id"], job["id"]),
                    )
                if payload["mode"] != "historical":
                    db.execute(
                        "update public.connections set status='healthy',last_sync_at=now(),"
                        "updated_at=now() where tenant_id=%s and id=%s",
                        (self.tenant_id, conn["id"]),
                    )

    def persist_record(
        self,
        db: psycopg.Connection[dict[str, Any]],
        conn: dict[str, Any],
        raw: dict[str, Any],
        record: dict[str, Any],
        run_id: UUID | None,
        correlation_id: UUID,
    ) -> UUID:
        args = (self.tenant_id, conn["id"], record["id"])
        prior = db.execute(
            "select * from public.external_records where tenant_id=%s "
            "and connection_id=%s and external_id=%s for update",
            args,
        ).fetchone()
        content_hash = digest(raw)
        if prior and prior["external_version"] > record["version"]:
            db.execute(
                "update public.deals set is_missing=false where tenant_id=%s and id=%s",
                (self.tenant_id, prior["deal_id"]),
            )
            db.execute(
                "update public.external_records set last_seen_run=coalesce(%s,last_seen_run) "
                "where tenant_id=%s and connection_id=%s and external_id=%s",
                (run_id, *args),
            )
            return UUID(str(prior["deal_id"]))
        if (
            prior
            and prior["external_version"] == record["version"]
            and prior["content_hash"] != content_hash
        ):
            raise IntegrationError("same_version_different_content", 422)
        deal_id = prior["deal_id"] if prior else uuid4()
        changed = not prior or prior["external_version"] < record["version"]
        namespace_id = f"{conn['id']}:{record['id']}"
        ref = {
            "provider": conn["provider"],
            "id": record["id"],
            "synthetic": record["synthetic"],
            "owner_id": record.get("owner_id"),
        }
        status = (
            record["canonical_stage"] if record["canonical_stage"] in {"won", "lost"} else "open"
        )
        db.execute(
            "insert into public.deals(id,tenant_id,connection_id,external_id,title,external_stage,"
            "canonical_stage,status,value,currency,external_version,source_changed_at,external_ref,"
            "source_authority,last_activity_at) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "'external',%s) on conflict(id) do update set title=excluded.title,"
            "external_stage=excluded.external_stage,canonical_stage=excluded.canonical_stage,"
            "status=excluded.status,value=excluded.value,currency=excluded.currency,"
            "external_version=excluded.external_version,source_changed_at=excluded.source_changed_at,"
            "external_ref=excluded.external_ref,is_missing=false,updated_at=now(),"
            "last_activity_at=excluded.last_activity_at,version=deals.version+%s",
            (
                deal_id,
                self.tenant_id,
                conn["id"],
                namespace_id,
                record["title"],
                record["stage"],
                record["canonical_stage"],
                status,
                record.get("value"),
                record.get("currency"),
                record["version"],
                record["changed_at"],
                Jsonb(ref),
                record["changed_at"],
                int(changed),
            ),
        )
        db.execute(
            "insert into public.external_records(tenant_id,connection_id,external_id,deal_id,"
            "external_version,content_hash,last_seen_run,source_changed_at) "
            "values(%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict(tenant_id,connection_id,entity_type,external_id) do update set "
            "external_version=excluded.external_version,content_hash=excluded.content_hash,"
            "last_seen_run=coalesce(excluded.last_seen_run,external_records.last_seen_run),"
            "source_changed_at=excluded.source_changed_at",
            (*args, deal_id, record["version"], content_hash, run_id, record["changed_at"]),
        )
        if changed:
            data = {**raw, "connection_id": str(conn["id"]), "status": status}
            event = db.execute(
                "insert into public.commercial_events(tenant_id,event_type,producer,aggregate_type,"
                "aggregate_id,provider_event_id,correlation_id,source,source_ref,occurred_at,data,"
                "payload_hash) values(%s,'deal.updated',%s,'deal',%s,%s,%s,'crm',%s,%s,%s,%s) "
                "on conflict do nothing returning id",
                (
                    self.tenant_id,
                    conn["provider"],
                    namespace_id,
                    f"{namespace_id}:v{record['version']}",
                    correlation_id,
                    f"{conn['provider']}:{record['id']}",
                    record["changed_at"],
                    Jsonb(data),
                    content_hash,
                ),
            ).fetchone()
            if event:
                db.execute(
                    "insert into public.jobs(tenant_id,kind,payload,correlation_id) "
                    "values(%s,'integration.project',%s,%s)",
                    (self.tenant_id, Jsonb({"event_id": str(event["id"])}), correlation_id),
                )
        return UUID(str(deal_id))

    def pipeline(self, user: AuthenticatedUser, cursor: UUID | None = None) -> dict[str, Any]:
        with self.db() as db:
            conn = self.connection(db)
            rows = (
                []
                if not conn
                else db.execute(
                    "select * from public.deals where tenant_id=%s and connection_id=%s "
                    "and (%s::uuid is null or id>%s) order by id limit 201",
                    (self.tenant_id, conn["id"], cursor, cursor),
                ).fetchall()
            )
            missing = (
                0
                if not conn
                else db.execute(
                    "select count(*) as n from public.deals where "
                    "tenant_id=%s and connection_id=%s "
                    "and is_missing",
                    (self.tenant_id, conn["id"]),
                ).fetchone()
            )
            missing_count = int(missing["n"]) if isinstance(missing, dict) else 0
            mapping = self.mapping(db, conn) if conn and conn["mapping_version"] else None
        enabled = bool(conn and conn["mapping_version"] and conn["status"] != "revoked")
        return {
            "items": [
                {
                    "id": row["id"],
                    "external_id": row["external_ref"]["id"],
                    "title": row["title"],
                    "stage": row["canonical_stage"],
                    "value": row["value"],
                    "currency": row["currency"],
                    "version": row["external_version"],
                    "owner_id": row["external_ref"].get("owner_id"),
                    "changed_at": row["source_changed_at"],
                    "synthetic": row["external_ref"].get("synthetic", False),
                    "is_missing": row["is_missing"],
                }
                for row in rows[:200]
            ],
            "stages": [{"id": s.canonical_stage, "label": s.label} for s in mapping.stages]
            if mapping
            else [
                {"id": s["canonical_stage"], "label": s["label"]}
                for s in suggested_mapping()["stages"]
            ],
            "capabilities": conn["capabilities"]
            if conn
            else {"read_deals": False, "update_stage": False},
            "permissions": {
                "can_move": enabled and user.role in {"admin", "manager"},
                "can_manage": user.role in {"admin", "manager"},
            },
            "freshness_at": conn["last_sync_at"] if conn else None,
            "source": "FakeCRM HTTP · dados sintéticos",
            "partial": bool(missing_count) or not conn or not conn["last_sync_at"],
            "missing_count": missing_count,
            "next_cursor": rows[199]["id"] if len(rows) > 200 else None,
            "connection": conn,
        }
