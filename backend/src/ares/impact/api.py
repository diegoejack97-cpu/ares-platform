from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from ares.auth.models import AuthenticatedUser
from ares.config import Settings
from ares.impact.export import render_report
from ares.impact.jobs import ExportJobs
from ares.impact.models import ImpactPage, ImpactSummary
from ares.impact.service import ImpactDenied, ImpactService


def impact_router(settings: Settings, require_user: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["M6 impact"])
    dependency = Depends(require_user)
    service = ImpactService(settings.database_url)
    jobs = ExportJobs(settings.database_url)

    def run(operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except ImpactDenied:
            raise HTTPException(403, detail={"code": "impact_unavailable"}) from None
        except psycopg.Error:
            raise HTTPException(503, detail={"code": "impact_unavailable"}) from None

    @router.get("/impact/summary", response_model=ImpactSummary)
    def summary(days: int = Query(30, ge=1, le=365), user: AuthenticatedUser = dependency) -> Any:
        return run(lambda: service.summary(user, days))

    @router.get("/impact/interventions", response_model=ImpactPage)
    def interventions(
        days: int = Query(30, ge=1, le=365),
        cursor: UUID | None = None,
        user: AuthenticatedUser = dependency,
    ) -> Any:
        return run(lambda: service.interventions(user, days, cursor))

    @router.get("/reports/impact/export")
    def export(
        background_tasks: BackgroundTasks,
        format: Literal["csv", "pdf"] = "csv",
        days: int = Query(30, ge=1, le=365),
        user: AuthenticatedUser = dependency,
    ) -> Any:
        def generate() -> Response:
            summary = service.summary(user, days)
            first = service.interventions(user, days, None, 500)
            if first["next_cursor"]:
                id = jobs.enqueue(user, format, days)
                background_tasks.add_task(jobs.build, user, id)
                return JSONResponse(
                    status_code=202,
                    content={
                        "id": str(id),
                        "status": "queued",
                        "download_path": f"/reports/exports/{id}",
                    },
                    headers={"Cache-Control": "no-store"},
                )
            rows: list[dict[str, Any]] = []
            cursor = None
            while True:
                page = service.interventions(user, days, cursor, 100)
                rows.extend(page["items"])
                cursor = page["next_cursor"]
                if not cursor:
                    break
            payload = render_report(summary, rows, format)
            correlation = service.audit_export(user, format, days, len(rows))
            return Response(
                payload,
                media_type="text/csv; charset=utf-8" if format == "csv" else "application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="ares-impacto.{format}"',
                    "Cache-Control": "no-store",
                    "X-Correlation-Id": str(correlation),
                },
            )

        return run(generate)

    @router.get("/reports/exports/{id}")
    def exported(
        id: UUID, background_tasks: BackgroundTasks, user: AuthenticatedUser = dependency
    ) -> Any:
        def retrieve() -> Response:
            job = jobs.get(user, id)
            if job["status"] == "failed":
                raise HTTPException(503, detail={"code": "export_failed"})
            if job["status"] != "ready":
                background_tasks.add_task(jobs.build, user, id)
                return JSONResponse(
                    status_code=202,
                    content={"status": job["status"]},
                    headers={"Cache-Control": "no-store"},
                )
            return Response(
                bytes(job["payload"]),
                media_type="text/csv; charset=utf-8"
                if job["format"] == "csv"
                else "application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="ares-impacto.{job["format"]}"',
                    "Cache-Control": "no-store",
                },
            )

        return run(retrieve)

    return router
