from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from ares.connectors.models import CRMCapabilities
from ares.decision.models import ActionDraft


@dataclass(frozen=True)
class PolicyResult:
    policy_set: str
    policy_version: int
    policy_hash: str
    verdict: Literal["allow", "require_approval", "deny"]
    rules_matched: list[str]
    obligations: list[str]
    required_role: str | None


class PolicyEngine:
    def __init__(self, policy_path: Path | None = None) -> None:
        self._path = policy_path or Path(__file__).parent / "policies" / "m3_actions.v1.json"
        raw = self._path.read_bytes()
        self._hash = hashlib.sha256(raw).hexdigest()
        self._policy: dict[str, Any] = json.loads(raw)

    def evaluate(
        self, action: ActionDraft, capabilities: CRMCapabilities, *, human_review: bool = False
    ) -> PolicyResult:
        capability = {
            "create_task": capabilities.create_task,
            "add_note": capabilities.add_note,
            "update_stage": capabilities.update_stage,
        }[action.action_kind]
        rule = self._policy["rules"][action.action_kind]
        verdict = cast(
            Literal["allow", "require_approval", "deny"],
            rule["verdict"] if capability else "deny",
        )
        matched = [f"action:{action.action_kind}"]
        obligations = list(rule.get("obligations", []))
        if not capability:
            matched.append("provider:capability_missing")
            obligations.append("disable_action_in_ui")
        policy_hash = self._hash
        version = int(self._policy["policy_version"])
        required_role = rule.get("required_role")
        if human_review and verdict != "deny":
            verdict = "require_approval"
            required_role = "manager"
            obligations.append("phase7_human_decision")
            version = 2
            policy_hash = hashlib.sha256((self._hash + ":phase7-human.v1").encode()).hexdigest()
        return PolicyResult(
            policy_set=str(self._policy["policy_set"]),
            policy_version=version,
            policy_hash=policy_hash,
            verdict=verdict,
            rules_matched=matched,
            obligations=obligations,
            required_role=required_role,
        )
