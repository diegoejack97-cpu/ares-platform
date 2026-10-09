"""Local M6 upgrade: preserve the running M4 sandbox and add durable lead writes.

All existing routes proxy to port 8010; only new lead records live in SQLite.
This is a development simulator, never a customer CRM adapter.
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import FastAPI, HTTPException, Request, Response

from ares.fake_crm_sandbox.models import CreateLeadRequest

app = FastAPI(title="ARES local M6 sandbox bridge")
DATABASE = Path("output/runtime/m6-sandbox-leads.sqlite")
UPSTREAM = "http://127.0.0.1:8010"


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request) -> Response:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower()
        in {
            "authorization",
            "idempotency-key",
            "x-correlation-id",
            "x-fakecrm-scenario",
            "content-type",
        }
    }
    async with httpx.AsyncClient(timeout=10) as client:
        if path == "v1/leads" and request.method == "POST":
            auth = await client.get(f"{UPSTREAM}/v1/capabilities", headers=headers)
            if auth.status_code != 200:
                return Response(
                    auth.content, status_code=auth.status_code, media_type="application/json"
                )
            key = request.headers.get("Idempotency-Key")
            if not key:
                raise HTTPException(400, detail={"code": "idempotency_key_required"})
            payload = CreateLeadRequest.model_validate(await request.json()).model_dump()
            fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            DATABASE.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(DATABASE) as db:
                db.execute(
                    "create table if not exists leads (key text primary key,"
                    "fingerprint text not null,payload text not null,external_id text not null)"
                )
                db.execute("begin immediate")
                previous = db.execute(
                    "select fingerprint,external_id from leads where key=?", (key,)
                ).fetchone()
                if previous and previous[0] != fingerprint:
                    raise HTTPException(409, detail={"code": "idempotency_conflict"})
                external_id = previous[1] if previous else f"lead-{uuid5(NAMESPACE_URL, key)}"
                if not previous:
                    db.execute(
                        "insert into leads values(?,?,?,?)",
                        (key, fingerprint, json.dumps(payload), external_id),
                    )
            return Response(
                json.dumps({"external_id": external_id, "duplicate": bool(previous)}),
                media_type="application/json",
            )
        upstream = await client.request(
            request.method,
            f"{UPSTREAM}/{path}",
            params=request.query_params,
            headers=headers,
            content=await request.body(),
        )
        if path == "v1/capabilities" and upstream.status_code == 200:
            return Response(
                json.dumps({**upstream.json(), "create_lead": True}), media_type="application/json"
            )
        return Response(
            upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type"),
        )
