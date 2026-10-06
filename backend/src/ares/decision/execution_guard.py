"""Revalidate the commercial contract immediately before an external write."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


class ExecutionBlocked(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def check_execution_contract(db: psycopg.Connection[Any], tenant_id: UUID) -> None:
    # Provider contract changes lock this same tenant row exclusively. Keep the
    # share lock through dispatch: a suspension preceding dispatch always wins;
    # a suspension arriving during an already-started write waits for its result.
    tenant = db.execute(
        "select status, timezone from public.tenants where id=%s for share", (tenant_id,)
    ).fetchone()
    if not tenant or tenant["status"] != "active":
        raise ExecutionBlocked("tenant_inactive")
    plan = db.execute(
        "select status, expires_at "
        "from public.tenant_entitlements where tenant_id=%s and module='ares_connect' for share",
        (tenant_id,),
    ).fetchone()
    if not plan or plan["status"] != "active":
        raise ExecutionBlocked("ares_connect_plan_inactive")
    billing = db.execute(
        "select state, grace_until from public.tenant_billing_state where tenant_id=%s for share",
        (tenant_id,),
    ).fetchone()
    if not billing:
        raise ExecutionBlocked("billing_unconfigured")
    if billing["state"] not in {"active", "past_due"}:
        raise ExecutionBlocked("billing_degraded")
    # now() is the transaction start and may precede a wait on any lock above.
    # Sample the server wall clock only after all authorization locks are held.
    clock = db.execute(
        "select clock_timestamp() as current_time, "
        "(clock_timestamp() at time zone %s)::date as today",
        (tenant["timezone"],),
    ).fetchone()
    assert clock is not None
    if plan["expires_at"] is not None and plan["expires_at"] <= clock["current_time"]:
        raise ExecutionBlocked("ares_connect_plan_inactive")
    if billing["state"] == "past_due" and (
        billing["grace_until"] is None or clock["today"] > billing["grace_until"]
    ):
        raise ExecutionBlocked("billing_degraded")


@contextmanager
def execution_contract(database_url: str, tenant_id: UUID) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as db:
        check_execution_contract(db, tenant_id)
        yield db
