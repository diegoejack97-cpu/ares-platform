"""Execution contracts and control-plane failures, without model calls."""

from dataclasses import FrozenInstanceError, replace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ares.agents.catalog import CATALOG, SEQUENCE, digest, validate_step
from ares.agents.contracts import AgentJob, AnalysisInput, RoutineCommand, StartAnalysis
from ares.agents.executor import AgnoExecutor
from ares.agents.runtime import AgentRuntime, AgentRuntimeError
from ares.api.app import app, require_user
from ares.auth.models import AuthenticatedUser


@pytest.fixture(autouse=True)
def clear_auth():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def principal():
    return AuthenticatedUser(user_id=uuid4(), tenant_id=uuid4(), role="admin")


def test_definitions_are_immutable_and_behavior_changes_hash():
    definition = CATALOG[SEQUENCE[0]]
    with pytest.raises(FrozenInstanceError):
        definition.objective = "changed"
    assert replace(definition, instructions="changed").definition_hash != definition.definition_hash
    assert len(definition.definition_hash) == 64
    assert digest({"b": 1, "a": 2}) == digest({"a": 2, "b": 1})


@pytest.mark.parametrize(
    "agent,depth,visited",
    [
        ("context-diagnosis", 0, ()),
        ("context-triage", 1, ("context-triage",)),
        ("context-diagnosis", 2, ()),
        ("unrestricted", 0, ()),
    ],
)
def test_loop_and_unknown_delegation_are_rejected(agent, depth, visited):
    with pytest.raises(ValueError, match="agent_sequence_forbidden"):
        validate_step(agent, depth, visited)


def test_request_cannot_choose_model_context_or_tenant():
    for extra in ("model_id", "tenant_id", "facts", "agent_id", "tools"):
        with pytest.raises(ValidationError):
            StartAnalysis.model_validate(
                {
                    "opportunity_id": uuid4(),
                    "context_ref": uuid4(),
                    "idempotency_key": uuid4(),
                    extra: "unsafe",
                }
            )
    with pytest.raises(ValidationError):
        AgentJob(workflow_id=uuid4(), agent_id="context-triage", depth=4)
    with pytest.raises(ValidationError):
        RoutineCommand(enabled=True, expected_version=0, reason="   ")


@pytest.mark.asyncio
async def test_no_key_degrades_explicitly_without_external_call():
    result = await AgnoExecutor("").execute(
        CATALOG[SEQUENCE[0]],
        AnalysisInput(context_ref=uuid4(), content_hash="hash", content="{}", evidence_refs=[]),
        "gpt-5.4",
    )
    assert result.degraded and result.usage.status == "not_called"
    assert result.output.needs_human_review


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/agents/catalog"),
        ("put", "/api/v1/agents/routines/context-analysis"),
        ("put", "/api/v1/agents/routines/context-analysis/specialists"),
        ("get", f"/api/v1/agents/opportunities/{uuid4()}/analysis"),
        ("post", "/api/v1/agents/workflows"),
        ("get", f"/api/v1/agents/workflows/{uuid4()}"),
        ("post", f"/api/v1/agents/workflows/{uuid4()}/cancel"),
    ],
)
def test_all_control_operations_require_authentication(method, path):
    assert getattr(TestClient(app), method)(path).status_code == 401


def test_errors_are_safe_and_correlated(monkeypatch):
    app.dependency_overrides[require_user] = principal

    def unavailable(*args):
        raise psycopg.OperationalError("private-secret-connection")

    monkeypatch.setattr(AgentRuntime, "routines", unavailable)
    response = TestClient(app).get("/api/v1/agents/catalog")
    assert response.status_code == 503
    assert "private-secret" not in response.text
    assert response.json()["error"]["correlation_id"]

    def denied(*args):
        raise AgentRuntimeError("agent_access_denied", 403)

    monkeypatch.setattr(AgentRuntime, "routines", denied)
    assert TestClient(app).get("/api/v1/agents/catalog").status_code == 403


def test_api_does_not_accept_context_injection():
    app.dependency_overrides[require_user] = principal
    response = TestClient(app).post(
        "/api/v1/agents/workflows",
        json={
            "opportunity_id": str(uuid4()),
            "context_ref": str(uuid4()),
            "idempotency_key": str(uuid4()),
            "facts": {"value": 99999},
        },
    )
    assert response.status_code == 422


def test_agno_adapter_uses_closed_tools_and_typed_output(monkeypatch):
    from types import SimpleNamespace

    import ares.agents.executor as module

    class FakeAgent:
        def __init__(self, **kwargs):
            assert kwargs["tools"] == [] and kwargs["tool_call_limit"] == 0
            assert not kwargs["search_knowledge"] and not kwargs["telemetry"]

        async def arun(self, payload):
            return SimpleNamespace(
                content={
                    "schema_version": "analysis-output.v1",
                    "summary": "Synthetic",
                    "evidence_refs": [],
                    "limitations": [],
                    "needs_human_review": True,
                },
                metrics=None,
            )

    monkeypatch.setattr(module, "Agent", FakeAgent)
    import asyncio

    result = asyncio.run(
        AgnoExecutor("synthetic-test-key").execute(
            CATALOG[SEQUENCE[0]],
            AnalysisInput(context_ref=uuid4(), content_hash="hash", content="{}", evidence_refs=[]),
            "gpt-5.4",
        )
    )
    assert result.output.summary == "Synthetic"
