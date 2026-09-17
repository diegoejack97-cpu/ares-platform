import asyncio
import base64
import json
from uuid import UUID

import httpx

from ares.config import Settings
from ares.provider.models import ProviderPrincipal
from ares.provider.service import ProviderDenied, ProviderService


class ProviderAuth:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def authenticate(self, token: str) -> ProviderPrincipal:
        if not self.settings.supabase_publishable_key or len(token) > 16_384:
            raise ProviderDenied
        # GoTrue verifies the JWT. Decode session_id only AFTER successful verification.
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                f"{self.settings.supabase_url.rstrip('/')}/auth/v1/user",
                headers={
                    "apikey": self.settings.supabase_publishable_key,
                    "Authorization": f"Bearer {token}",
                },
            )
        if response.status_code != 200:
            raise ProviderDenied
        try:
            payload = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            user_id = UUID(response.json()["id"])
            if UUID(claims["sub"]) != user_id:
                raise ProviderDenied
            principal = ProviderPrincipal(user_id=user_id, session_id=UUID(claims["session_id"]))
        except (ValueError, KeyError, TypeError, IndexError):
            raise ProviderDenied from None
        await asyncio.to_thread(self.validate, principal)
        return principal

    def validate(self, principal: ProviderPrincipal) -> None:
        service = ProviderService(self.settings.database_url)
        with service.db() as db:
            service.authorize(db, principal)
