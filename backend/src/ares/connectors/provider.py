from typing import Protocol

from ares.event_journal.models import IncomingCRMEvent


class CRMWebhookProvider(Protocol):
    def sign(self, raw_body: bytes) -> str: ...

    def verify_and_normalize(self, raw_body: bytes, signature: str | None) -> IncomingCRMEvent: ...
