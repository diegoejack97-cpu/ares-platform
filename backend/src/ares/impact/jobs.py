# ruff: noqa: E501
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from ares.auth.models import AuthenticatedUser
from ares.impact.export import render_report
from ares.impact.service import ImpactDenied, ImpactService


class ExportJobs:
    def __init__(self, url: str):
        self.url = url
        self.service = ImpactService(url)

    def enqueue(self, user: AuthenticatedUser, format: str, days: int) -> UUID:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            self.service.authorize(db, user)
            db.execute(
                "update public.report_exports set payload=null where expires_at<=now() and payload is not null"
            )
            row = db.execute(
                "insert into public.report_exports(tenant_id,owner_id,format,days) values(%s,%s,%s,%s) returning id",
                (user.tenant_id, user.user_id, format, days),
            ).fetchone()
            assert row
            return UUID(str(row["id"]))

    def get(self, user: AuthenticatedUser, id: UUID) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as db:
            self.service.authorize(db, user)
            row = db.execute(
                "select * from public.report_exports where id=%s and tenant_id=%s and owner_id=%s and expires_at>now()",
                (id, user.tenant_id, user.user_id),
            ).fetchone()
            if not row:
                raise ImpactDenied
            return dict(row)

    def build(self, user: AuthenticatedUser, id: UUID) -> None:
        with psycopg.connect(self.url, autocommit=True) as lock:
            key = f"report-export:{id}"
            acquired = lock.execute("select pg_try_advisory_lock(hashtext(%s))", (key,)).fetchone()
            if not acquired or not acquired[0]:
                return
            try:
                job = self.get(user, id)
                if job["status"] == "ready":
                    return
                lock.execute(
                    "update public.report_exports set status='running',updated_at=now() where id=%s",
                    (id,),
                )
                summary = self.service.summary(user, job["days"])
                rows = []
                cursor = None
                while True:
                    page = self.service.interventions(user, job["days"], cursor, 100)
                    rows.extend(page["items"])
                    cursor = page["next_cursor"]
                    if not cursor:
                        break
                payload = render_report(summary, rows, job["format"])
                self.get(user, id)
                self.service.audit_export(user, job["format"], job["days"], len(rows))
                lock.execute(
                    "update public.report_exports set status='ready',payload=%s,updated_at=now() where id=%s and expires_at>now()",
                    (payload, id),
                )
            except Exception:
                lock.execute(
                    "update public.report_exports set status='failed',payload=null,updated_at=now() where id=%s",
                    (id,),
                )
            finally:
                lock.execute("select pg_advisory_unlock(hashtext(%s))", (key,))
