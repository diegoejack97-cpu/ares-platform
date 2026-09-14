from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from ares.api.app import app, require_user
from ares.auth.models import AuthenticatedUser
from ares.graph.service import GraphService, GraphUnavailable


@pytest.fixture(autouse=True)
def clean_auth():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def user():
    return AuthenticatedUser(user_id=uuid4(), tenant_id=uuid4(), role="seller")


def test_graph_requires_authentication():
    assert TestClient(app).get(f"/api/v1/opportunities/{uuid4()}/graph").status_code == 401


@pytest.mark.parametrize("depth", [0, 3, "oops"])
def test_graph_depth_is_bounded(depth):
    app.dependency_overrides[require_user] = user
    response = TestClient(app).get(f"/api/v1/opportunities/{uuid4()}/graph?depth={depth}")
    assert response.status_code == 422


@pytest.mark.parametrize("error,status", [(GraphUnavailable, 404), (psycopg.OperationalError, 503)])
def test_graph_errors_do_not_disclose_database_or_tenant(monkeypatch, error, status):
    def unavailable(*args):
        raise error("private data")

    monkeypatch.setattr(GraphService, "read", unavailable)
    app.dependency_overrides[require_user] = user
    response = TestClient(app).get(f"/api/v1/opportunities/{uuid4()}/graph")
    assert response.status_code == status
    assert "private data" not in response.text
    assert response.json()["error"]["correlation_id"]
