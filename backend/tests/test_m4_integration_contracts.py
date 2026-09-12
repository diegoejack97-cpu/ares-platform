from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ares.auth.models import AuthenticatedUser
from ares.connectors.http_fake_crm import CRMProviderRequestError
from ares.connectors.models import CRMDeal, CRMWriteResult
from ares.integrations.models import (
    MappingCommand,
    StageCommand,
    SyncCommand,
    digest,
    normalize,
    suggested_mapping,
)
from ares.integrations.pipeline import PipelineService
from ares.integrations.service import IntegrationError, IntegrationService


def mapping_payload() -> dict[str, Any]:
    return {"expected_version": 0, **suggested_mapping()}


def raw_deal() -> dict[str, Any]:
    return {
        "id": "synthetic-deal",
        "title": "Synthetic contract",
        "stage": "proposal",
        "version": 2,
        "changed_at": "2026-09-01T12:00:00+00:00",
        "value": None,
        "currency": None,
        "owner_id": None,
        "synthetic": True,
    }


def test_suggested_mapping_is_complete_versioned_and_preserves_missing_money() -> None:
    mapping = MappingCommand.model_validate(mapping_payload())
    record = normalize(raw_deal(), mapping)
    assert mapping.expected_version == 0
    assert len(mapping.stages) == 6
    assert record["value"] is None and record["currency"] is None
    assert record["canonical_stage"] == "proposal"
    assert record["changed_at"].tzinfo == UTC
    assert record["synthetic"] is True


def test_mapping_rejects_missing_or_duplicate_canonical_fields() -> None:
    payload = mapping_payload()
    payload["fields"] = [f for f in payload["fields"] if f["canonical_field"] != "title"]
    with pytest.raises(ValidationError, match="invalid_canonical_fields"):
        MappingCommand.model_validate(payload)
    payload = mapping_payload()
    payload["fields"][0] = deepcopy(payload["fields"][1])
    with pytest.raises(ValidationError, match="invalid_canonical_fields"):
        MappingCommand.model_validate(payload)


@pytest.mark.parametrize("name", ["id", "title", "stage", "version", "changed_at"])
def test_required_mapping_fields_cannot_be_optional(name: str) -> None:
    payload = mapping_payload()
    next(f for f in payload["fields"] if f["canonical_field"] == name)["required"] = False
    with pytest.raises(ValidationError, match="required_field_cannot_be_optional"):
        MappingCommand.model_validate(payload)


@pytest.mark.parametrize("name", ["id", "version", "changed_at"])
@pytest.mark.parametrize(
    "attribute,value", [("provider_path", "alternate"), ("transformation", "uppercase")]
)
def test_source_identity_and_ordering_cannot_be_remapped(
    name: str,
    attribute: str,
    value: str,
) -> None:
    payload = mapping_payload()
    next(f for f in payload["fields"] if f["canonical_field"] == name)[attribute] = value
    with pytest.raises(ValidationError, match="source_identity_and_version_are_immutable"):
        MappingCommand.model_validate(payload)


@pytest.mark.parametrize("attribute", ["external_stage", "canonical_stage", "position"])
def test_ambiguous_stage_mappings_are_rejected(attribute: str) -> None:
    payload = mapping_payload()
    payload["stages"][1][attribute] = payload["stages"][0][attribute]
    with pytest.raises(ValidationError, match="ambiguous_stage_mapping"):
        MappingCommand.model_validate(payload)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("title", None, "required_source_field_missing"),
        ("stage", "not-mapped", "unmapped_source_stage"),
        ("version", True, "invalid_source_version"),
        ("version", 0, "invalid_source_version"),
        ("changed_at", "2026-09-01T12:00:00", "source_timezone_required"),
        ("value", True, "invalid_source_value"),
        ("value", -1, "invalid_source_value"),
        ("value", float("nan"), "invalid_source_value"),
        ("value", float("inf"), "invalid_source_value"),
        ("currency", "brl", "invalid_source_currency"),
    ],
)
def test_invalid_source_payloads_are_not_silently_normalized(
    field: str,
    value: Any,
    error: str,
) -> None:
    raw = {**raw_deal(), field: value}
    with pytest.raises(ValueError, match=error):
        normalize(raw, MappingCommand.model_validate(mapping_payload()))


def test_currency_transform_is_explicit_and_zero_is_not_missing() -> None:
    payload = mapping_payload()
    next(f for f in payload["fields"] if f["canonical_field"] == "currency")["transformation"] = (
        "uppercase"
    )
    record = normalize(
        {**raw_deal(), "currency": "brl", "value": 0}, MappingCommand.model_validate(payload)
    )
    assert record["currency"] == "BRL" and record["value"] == 0


def test_historical_window_accepts_six_months_and_requires_aware_bounds() -> None:
    until = datetime.now(UTC) - timedelta(days=1)
    command = SyncCommand(mode="historical", since=until - timedelta(days=186), until=until)
    assert command.mode == "historical"
    with pytest.raises(ValidationError, match="historical_window_required"):
        SyncCommand(mode="historical")
    with pytest.raises(ValidationError, match="timezone_required"):
        SyncCommand(mode="historical", since=until.replace(tzinfo=None), until=until)


@pytest.mark.parametrize("days", [0, -1, 187])
def test_historical_window_rejects_empty_reversed_or_oversized_ranges(days: int) -> None:
    until = datetime.now(UTC) - timedelta(days=1)
    with pytest.raises(ValidationError, match="historical_window_maximum_186_days"):
        SyncCommand(mode="historical", since=until - timedelta(days=days), until=until)


def test_custom_ranges_cannot_override_incremental_checkpoint_or_reconciliation() -> None:
    now = datetime.now(UTC)
    for mode in ("incremental", "reconcile"):
        with pytest.raises(ValidationError, match="window_only_for_historical"):
            SyncCommand.model_validate({"mode": mode, "since": now})
    with pytest.raises(ValidationError, match="historical_window_in_future"):
        SyncCommand(mode="historical", since=now, until=now + timedelta(days=1))


class RecordingDatabase:
    def __init__(self, prior: dict[str, Any] | None = None) -> None:
        self.prior = prior
        self.calls: list[tuple[str, Any]] = []

    def execute(self, sql: str, args: Any = None) -> Mock:
        self.calls.append((sql, args))
        row = self.prior if sql.startswith("select * from public.external_records") else None
        if sql.startswith("insert into public.commercial_events"):
            row = {"id": uuid4()}
        return Mock(fetchone=Mock(return_value=row))


def test_out_of_order_source_version_never_overwrites_projection_or_emits_event() -> None:
    deal_id = uuid4()
    db = RecordingDatabase({"external_version": 3, "deal_id": deal_id})
    provider = Mock()
    service = IntegrationService("not-used", uuid4(), provider)
    raw = raw_deal()
    record = normalize(raw, MappingCommand.model_validate(mapping_payload()))
    result = service.persist_record(
        cast(Any, db), {"id": uuid4(), "provider": "fake-crm-http"}, raw, record, uuid4(), uuid4()
    )
    assert result == deal_id
    assert not any(sql.startswith("insert into public.deals") for sql, _ in db.calls)
    assert not any("commercial_events" in sql for sql, _ in db.calls)
    assert any("last_seen_run" in sql for sql, _ in db.calls)
    provider.assert_not_called()


def test_same_version_changed_content_is_quarantined_before_projection_mutation() -> None:
    raw = raw_deal()
    db = RecordingDatabase({"external_version": 2, "deal_id": uuid4(), "content_hash": "different"})
    service = IntegrationService("not-used", uuid4(), Mock())
    with pytest.raises(IntegrationError, match="same_version_different_content"):
        service.persist_record(
            cast(Any, db),
            {"id": uuid4(), "provider": "fake-crm-http"},
            raw,
            normalize(raw, MappingCommand.model_validate(mapping_payload())),
            uuid4(),
            uuid4(),
        )
    assert len(db.calls) == 1


def test_replayed_source_version_does_not_duplicate_journal_or_projection_jobs() -> None:
    raw = raw_deal()
    db = RecordingDatabase({"external_version": 2, "deal_id": uuid4(), "content_hash": digest(raw)})
    service = IntegrationService("not-used", uuid4(), Mock())
    service.persist_record(
        cast(Any, db),
        {"id": uuid4(), "provider": "fake-crm-http"},
        raw,
        normalize(raw, MappingCommand.model_validate(mapping_payload())),
        uuid4(),
        uuid4(),
    )
    assert not any(
        "commercial_events" in sql or "insert into public.jobs" in sql for sql, _ in db.calls
    )


def test_unconfirmed_human_command_is_rejected_before_database_or_remote_io() -> None:
    tenant_id = uuid4()
    service = PipelineService("not-a-database", tenant_id, Mock())
    user = AuthenticatedUser(
        user_id=uuid4(), tenant_id=tenant_id, role="manager", email="test@local"
    )
    command = StageCommand(
        stage="won", expected_version=1, idempotency_key=uuid4(), confirmed=False
    )
    with pytest.raises(IntegrationError, match="explicit_confirmation_required"):
        service.move(user, uuid4(), command)


@pytest.mark.parametrize("role", ["seller", "auditor"])
def test_read_only_roles_cannot_issue_pipeline_commands(role: str) -> None:
    tenant_id = uuid4()
    service = PipelineService("not-a-database", tenant_id, Mock())
    user = AuthenticatedUser.model_validate(
        {"user_id": uuid4(), "tenant_id": tenant_id, "role": role, "email": "test@local"}
    )
    command = StageCommand(stage="won", expected_version=1, idempotency_key=uuid4(), confirmed=True)
    with pytest.raises(IntegrationError, match="manager_required"):
        service.move(user, uuid4(), command)


class IntentDatabase:
    def __init__(self, prior: dict[str, Any]) -> None:
        self.prior = prior
        self.calls: list[tuple[str, Any]] = []

    def __enter__(self) -> "IntentDatabase":
        return self

    def __exit__(self, *_args: Any) -> None:
        pass

    def execute(self, sql: str, args: Any = None) -> Mock:
        self.calls.append((sql, args))
        row = self.prior if sql.startswith("select * from public.external_write_dedup") else None
        return Mock(fetchone=Mock(return_value=row))


def pending_intent_service(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    PipelineService,
    AuthenticatedUser,
    Any,
    StageCommand,
    Mock,
    IntentDatabase,
]:
    tenant_id, deal_id = uuid4(), uuid4()
    user = AuthenticatedUser(user_id=uuid4(), tenant_id=tenant_id, role="manager")
    command = StageCommand(stage="won", expected_version=1, idempotency_key=uuid4(), confirmed=True)
    request = {
        **command.model_dump(mode="json"),
        "deal_id": str(deal_id),
        "actor_id": str(user.user_id),
    }
    prior = {
        "id": uuid4(),
        "status": "pending",
        "fingerprint": digest(request),
        "state_before": {"external_ref": {"id": "synthetic-deal"}, "external_stage": "new"},
        "request_json": {"external_stage": "won"},
        "correlation_id": uuid4(),
    }
    db = IntentDatabase(prior)
    provider = Mock()
    provider.update_deal_stage.return_value = CRMWriteResult(external_id="stage-synthetic-deal-v2")
    service = PipelineService("not-used", tenant_id, provider)
    monkeypatch.setattr(service, "db", lambda: db)
    monkeypatch.setattr(
        service,
        "connection",
        lambda _db: {
            "id": uuid4(),
            "status": "healthy",
            "mapping_version": 1,
            "capabilities": {"update_stage": True},
        },
    )
    return service, user, deal_id, command, provider, db


def test_remote_accepted_but_confirmation_404_is_uncertain_not_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, user, deal_id, command, provider, db = pending_intent_service(monkeypatch)
    provider.get_deal.side_effect = CRMProviderRequestError(
        "Not found after accepted write",
        status_code=404,
        code="deal_not_found",
    )
    with pytest.raises(IntegrationError) as failure:
        service._move_locked(user, deal_id, command)
    assert failure.value.status == 503
    writes = [
        args for sql, args in db.calls if sql.startswith("update public.external_write_dedup")
    ]
    assert writes[0][0] == "uncertain"
    assert provider.correlation_id == str(db.prior["correlation_id"])
    provider.update_deal_stage.assert_called_once_with(
        "synthetic-deal",
        "won",
        str(command.idempotency_key),
        1,
    )
    assert not any("pipeline.executed" in sql for sql, _ in db.calls)


def test_remote_version_rejection_stays_conflict_and_does_not_read_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, user, deal_id, command, provider, db = pending_intent_service(monkeypatch)
    provider.update_deal_stage.side_effect = CRMProviderRequestError(
        "Stale version",
        status_code=409,
        code="version_conflict",
    )
    with pytest.raises(IntegrationError) as failure:
        service._move_locked(user, deal_id, command)
    assert failure.value.status == 409
    writes = [
        args for sql, args in db.calls if sql.startswith("update public.external_write_dedup")
    ]
    assert writes[0][0] == "conflict"
    provider.get_deal.assert_not_called()


@pytest.mark.parametrize("field,value", [("id", "wrong-deal"), ("stage", "lost"), ("version", 1)])
def test_divergent_confirmation_cannot_be_reported_as_success(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    service, user, deal_id, command, provider, db = pending_intent_service(monkeypatch)
    provider.get_deal.return_value = CRMDeal.model_validate(
        {
            **raw_deal(),
            "stage": "won",
            "value": 1,
            "currency": "BRL",
            field: value,
        }
    )
    with pytest.raises(IntegrationError, match="source_confirmation_diverged") as failure:
        service._move_locked(user, deal_id, command)
    assert failure.value.status == 503
    writes = [
        args for sql, args in db.calls if sql.startswith("update public.external_write_dedup")
    ]
    assert writes[0][0] == "uncertain"


def test_completed_intent_replay_never_executes_remote_command_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, user, deal_id, command, provider, db = pending_intent_service(monkeypatch)
    db.prior.update(status="succeeded", response_json={"status": "succeeded", "duplicate": False})
    assert service._move_locked(user, deal_id, command) == {
        "status": "succeeded",
        "duplicate": True,
    }
    provider.update_deal_stage.assert_not_called()
