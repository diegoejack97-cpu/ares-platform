import base64
import json
from uuid import uuid4

import pytest

from ares.config import Settings
from ares.provider.auth import ProviderAuth
from ares.provider.service import ProviderDenied


def token(claims):
    return (
        "header."
        + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        + ".signature"
    )


@pytest.mark.asyncio
async def test_session_claim_is_used_only_after_gotrue_validation(monkeypatch):
    user, session = uuid4(), uuid4()
    received = []
    auth = ProviderAuth(Settings(supabase_publishable_key="synthetic"))
    monkeypatch.setattr(auth, "validate", received.append)
    status = 401

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            class Response:
                status_code = status

                def json(self):
                    return {"id": str(user), "user_metadata": {"provider": True}}

            return Response()

    monkeypatch.setattr("ares.provider.auth.httpx.AsyncClient", Client)
    signed = token({"sub": str(user), "session_id": str(session)})
    with pytest.raises(ProviderDenied):
        await auth.authenticate(signed)
    assert received == []
    status = 200
    result = await auth.authenticate(signed)
    assert result.user_id == user and result.session_id == session
    assert received == [result]
    for invalid in [
        token({"sub": str(uuid4()), "session_id": str(session)}),
        token({"sub": str(user)}),
        "malformed",
    ]:
        with pytest.raises(ProviderDenied):
            await auth.authenticate(invalid)
    assert received == [result]
