"""Approval roles are checked against persisted membership, never client metadata."""

from __future__ import annotations


class DecisionAuthorizationError(Exception):
    def __init__(self, code: str = "decision_actor_forbidden") -> None:
        super().__init__(code)
        self.code = code


def role_can_decide(role: str | None, required_role: str | None) -> bool:
    # An auditor cannot mutate a recommendation. Unknown/missing policy roles deny.
    allowed = {
        "admin": {"admin"},
        "manager": {"admin", "manager"},
        "seller": {"admin", "manager", "seller"},
    }
    return role in allowed.get(required_role or "", set())
