import hashlib
import hmac

from fastapi import HTTPException, status
from pydantic import ValidationError

from ares.event_journal.models import IncomingCRMEvent


class FakeCRMProvider:
    def __init__(self, webhook_secret: str) -> None:
        self._secret = webhook_secret.encode()

    def sign(self, raw_body: bytes) -> str:
        digest = hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def verify_and_normalize(
        self,
        raw_body: bytes,
        signature: str | None,
    ) -> IncomingCRMEvent:
        expected = self.sign(raw_body)
        if signature is None or not hmac.compare_digest(signature, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid FakeCRM webhook signature",
            )
        try:
            return IncomingCRMEvent.model_validate_json(raw_body)
        except ValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error.errors(include_url=False),
            ) from error
