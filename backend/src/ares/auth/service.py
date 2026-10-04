import asyncio
from typing import Any, cast
from uuid import UUID

import httpx
import psycopg

from ares.auth.models import AuthenticatedUser


class SupabaseAuthService:
    def __init__(self, supabase_url: str, publishable_key: str, database_url: str) -> None:
        self._supabase_url = supabase_url.rstrip("/")
        self._publishable_key = publishable_key
        self._database_url = database_url

    async def authenticate(self, access_token: str) -> AuthenticatedUser | None:
        if not self._publishable_key:
            return None
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{self._supabase_url}/auth/v1/user",
                headers={
                    "apikey": self._publishable_key,
                    "Authorization": f"Bearer {access_token}",
                },
            )
        if response.status_code != 200:
            return None
        payload: dict[str, Any] = response.json()
        app_metadata = payload.get("app_metadata") or {}
        tenant_value = app_metadata.get("active_tenant_id")
        try:
            user_id = UUID(str(payload["id"]))
            tenant_id = UUID(str(tenant_value))
        except (KeyError, TypeError, ValueError):
            return None
        role = await asyncio.to_thread(self._membership_role, user_id, tenant_id)
        if role not in {"admin", "manager", "seller", "auditor"}:
            return None
        return AuthenticatedUser(
            user_id=user_id,
            email=payload.get("email"),
            tenant_id=tenant_id,
            role=cast(Any, role),
        )

    def _membership_role(self, user_id: UUID, tenant_id: UUID) -> str | None:
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                select role::text
                from public.memberships m
                join public.tenants t on t.id=m.tenant_id
                where m.user_id = %s and m.tenant_id = %s and m.active
                  and t.status = 'active'
                """,
                (user_id, tenant_id),
            ).fetchone()
        return None if row is None else str(row[0])

    def has_connect_access(self, tenant_id: UUID) -> bool:
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                select exists(
                    select 1 from public.tenant_entitlements
                    where tenant_id=%s and module='ares_connect' and status='active'
                      and (expires_at is null or expires_at>now())
                )
                """,
                (tenant_id,),
            ).fetchone()
        return bool(row and row[0])
