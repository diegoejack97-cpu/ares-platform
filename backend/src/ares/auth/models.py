from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AuthenticatedUser(BaseModel):
    user_id: UUID
    email: str | None = None
    tenant_id: UUID
    role: Literal["admin", "manager", "seller", "auditor"]
