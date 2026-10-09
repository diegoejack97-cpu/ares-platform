"""Database acceptance for the recurring SLA sentinel (requires local Supabase)."""

import os
from datetime import UTC, datetime, time
from uuid import UUID, uuid4

import psycopg
import pytest

from ares.sentinels.models import SentinelRuleCommand, SentinelScheduleCommand
from ares.sentinels.service import (
    RULE_ID,
    SentinelScheduleConflict,
    SentinelService,
)

DATABASE_URL = os.getenv("ARES_TEST_DATABASE_URL")
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="local Supabase database is not configured")
def test_sentinel_schedule_is_versioned_audited_and_limited_by_plan() -> None:
    assert DATABASE_URL is not None
    service = SentinelService(DATABASE_URL)
    actor = uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        prior = connection.execute(
            "select enabled,interval_minutes,start_time_local,next_run_at,version,"
            "updated_at,updated_by from public.sentinel_schedules "
            "where tenant_id=%s and rule_id=%s",
            (TENANT_ID, RULE_ID),
        ).fetchone()
        slots = connection.execute(
            "select sentinel_slots from public.tenant_quotas where tenant_id=%s",
            (TENANT_ID,),
        ).fetchone()
        assert prior is not None and slots is not None
        connection.execute(
            "update public.tenant_quotas set sentinel_slots=1 where tenant_id=%s",
            (TENANT_ID,),
        )

    try:
        command = SentinelScheduleCommand(
            expected_version=prior[4],
            enabled=True,
            interval_minutes=60 if prior[1] != 60 else 120,
            start_time_local=time(8, 30),
            reason="Teste de programação",
        )
        updated = service.update_schedule_sync(TENANT_ID, actor, command)
        assert updated["version"] == prior[4] + 1
        assert updated["interval_minutes"] == command.interval_minutes
        assert service.schedule_sync(TENANT_ID)["timezone"]
        with psycopg.connect(DATABASE_URL) as connection:
            audit = connection.execute(
                "select prior_config,next_config from public.sentinel_schedule_audit "
                "where tenant_id=%s and rule_id=%s and actor_user_id=%s",
                (TENANT_ID, RULE_ID, actor),
            ).fetchone()
            assert audit is not None
            assert audit[0]["version"] == prior[4]
            assert audit[1]["version"] == updated["version"]
        with pytest.raises(SentinelScheduleConflict, match="stale_sentinel_schedule"):
            service.update_schedule_sync(TENANT_ID, actor, command)

        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "update public.tenant_quotas set sentinel_slots=0 where tenant_id=%s",
                (TENANT_ID,),
            )
        with pytest.raises(SentinelScheduleConflict, match="sentinel_capacity_unavailable"):
            service.update_schedule_sync(
                TENANT_ID,
                actor,
                SentinelScheduleCommand(
                    expected_version=updated["version"],
                    enabled=True,
                    interval_minutes=60,
                    start_time_local=time(9, 0),
                    reason="Plano sem capacidade",
                ),
            )
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "update public.sentinel_schedules set enabled=%s,interval_minutes=%s,"
                "start_time_local=%s,next_run_at=%s,version=%s,updated_at=%s,"
                "updated_by=%s where tenant_id=%s and rule_id=%s",
                (*prior, TENANT_ID, RULE_ID),
            )
            connection.execute(
                "delete from public.sentinel_schedule_audit where tenant_id=%s "
                "and rule_id=%s and actor_user_id=%s",
                (TENANT_ID, RULE_ID, actor),
            )
            connection.execute(
                "update public.tenant_quotas set sentinel_slots=%s where tenant_id=%s",
                (slots[0], TENANT_ID),
            )


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="local Supabase database is not configured")
def test_sla_sentinel_records_one_finding_per_deadline_and_only_current_findings() -> None:
    assert DATABASE_URL is not None
    service = SentinelService(DATABASE_URL)
    external_id = f"sentinel-test-{uuid4()}"
    first_due = datetime(2000, 1, 1, tzinfo=UTC)
    second_due = datetime(2001, 1, 1, tzinfo=UTC)
    with psycopg.connect(DATABASE_URL) as connection:
        entitled = connection.execute(
            "select 1 from public.tenant_entitlements where tenant_id=%s "
            "and module='ares_connect' and status='active' "
            "and (expires_at is null or expires_at>now())",
            (TENANT_ID,),
        ).fetchone()
    if not entitled:
        pytest.skip("seed tenant has no active Connect entitlement")

    with psycopg.connect(DATABASE_URL) as connection:
        prior_schedule = connection.execute(
            "select enabled,next_run_at,last_run_at,last_created_count "
            "from public.sentinel_schedules where tenant_id=%s and rule_id=%s",
            (TENANT_ID, RULE_ID),
        ).fetchone()
        assert prior_schedule is not None
        connection.execute(
            "update public.sentinel_schedules set enabled=true,"
            "next_run_at=now()-interval '1 second' "
            "where tenant_id=%s and rule_id=%s",
            (TENANT_ID, RULE_ID),
        )

    with psycopg.connect(DATABASE_URL) as connection:
        deal_id = connection.execute(
            "insert into public.deals(tenant_id,title,external_id) "
            "values(%s,'Caso sintético de sentinela',%s) returning id",
            (TENANT_ID, external_id),
        ).fetchone()[0]
        opportunity_id = connection.execute(
            "insert into public.ares_opportunities"
            "(tenant_id,deal_id,opportunity_type,state,sla_at) "
            "values(%s,%s,'sentinel_test','detected',%s) returning id",
            (TENANT_ID, deal_id, first_due),
        ).fetchone()[0]

    try:
        with psycopg.connect(DATABASE_URL) as connection:
            prior_slots = connection.execute(
                "select sentinel_slots from public.tenant_quotas where tenant_id=%s",
                (TENANT_ID,),
            ).fetchone()[0]
            connection.execute(
                "update public.tenant_quotas set sentinel_slots=0 where tenant_id=%s",
                (TENANT_ID,),
            )
        try:
            service.scan_sync()
            with psycopg.connect(DATABASE_URL) as connection:
                assert (
                    connection.execute(
                        "select count(*) from public.sentinel_findings "
                        "where tenant_id=%s and opportunity_id=%s and rule_id=%s",
                        (TENANT_ID, opportunity_id, RULE_ID),
                    ).fetchone()[0]
                    == 0
                )
        finally:
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute(
                    "update public.tenant_quotas set sentinel_slots=%s where tenant_id=%s",
                    (prior_slots, TENANT_ID),
                )
                connection.execute(
                    "update public.sentinel_schedules set next_run_at=now()-interval '1 second' "
                    "where tenant_id=%s and rule_id=%s",
                    (TENANT_ID, RULE_ID),
                )
        service.scan_sync()
        service.scan_sync()
        with psycopg.connect(DATABASE_URL) as connection:
            count = connection.execute(
                "select count(*) from public.sentinel_findings "
                "where tenant_id=%s and opportunity_id=%s and rule_id=%s",
                (TENANT_ID, opportunity_id, RULE_ID),
            ).fetchone()[0]
        assert count == 1
        assert any(
            item["opportunity_id"] == opportunity_id
            for item in service.list_sync(TENANT_ID, limit=50)["items"]
        )

        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "update public.ares_opportunities set sla_at=%s where id=%s and tenant_id=%s",
                (second_due, opportunity_id, TENANT_ID),
            )
            connection.execute(
                "update public.sentinel_schedules set next_run_at=now()-interval '1 second' "
                "where tenant_id=%s and rule_id=%s",
                (TENANT_ID, RULE_ID),
            )
        service.scan_sync()
        with psycopg.connect(DATABASE_URL) as connection:
            count = connection.execute(
                "select count(*) from public.sentinel_findings "
                "where tenant_id=%s and opportunity_id=%s and rule_id=%s",
                (TENANT_ID, opportunity_id, RULE_ID),
            ).fetchone()[0]
        assert count == 2
        assert (
            sum(
                item["opportunity_id"] == opportunity_id
                for item in service.list_sync(TENANT_ID, limit=50)["items"]
            )
            == 1
        )

        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "update public.ares_opportunities set state='closed' where id=%s and tenant_id=%s",
                (opportunity_id, TENANT_ID),
            )
        assert not any(
            item["opportunity_id"] == opportunity_id
            for item in service.list_sync(TENANT_ID, limit=50)["items"]
        )
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "update public.sentinel_schedules set enabled=%s,next_run_at=%s,"
                "last_run_at=%s,last_created_count=%s "
                "where tenant_id=%s and rule_id=%s",
                (*prior_schedule, TENANT_ID, RULE_ID),
            )
            connection.execute(
                "delete from public.sentinel_findings where tenant_id=%s and opportunity_id=%s",
                (TENANT_ID, opportunity_id),
            )
            connection.execute(
                "delete from public.ares_opportunities where tenant_id=%s and id=%s",
                (TENANT_ID, opportunity_id),
            )
            connection.execute(
                "delete from public.deals where tenant_id=%s and id=%s",
                (TENANT_ID, deal_id),
            )


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="local Supabase database is not configured")
def test_configured_rules_are_audited_scanned_and_tenant_scoped() -> None:
    assert DATABASE_URL is not None
    service = SentinelService(DATABASE_URL)
    actor = uuid4()
    rule_ids: list[str] = []
    opportunity_id = None
    deal_id = None
    with psycopg.connect(DATABASE_URL) as connection:
        prior_slots = connection.execute(
            "select sentinel_slots from public.tenant_quotas where tenant_id=%s",
            (TENANT_ID,),
        ).fetchone()
        prior_active = connection.execute(
            "select count(*) from public.sentinel_schedules "
            "where tenant_id=%s and enabled and archived_at is null",
            (TENANT_ID,),
        ).fetchone()[0]
        entitled = connection.execute(
            "select 1 from public.tenant_entitlements where tenant_id=%s "
            "and module='ares_connect' and status='active' "
            "and (expires_at is null or expires_at>now())",
            (TENANT_ID,),
        ).fetchone()
    if prior_slots is None or not entitled:
        pytest.skip("seed tenant is not ready for Connect sentinel scans")

    try:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "update public.tenant_quotas set sentinel_slots=%s where tenant_id=%s",
                (prior_active + 2, TENANT_ID),
            )
            deal_id = connection.execute(
                "insert into public.deals(tenant_id,title,external_id) "
                "values(%s,'Synthetic configured sentinel',%s) returning id",
                (TENANT_ID, f"sentinel-config-{uuid4()}"),
            ).fetchone()[0]
            opportunity_id = connection.execute(
                "insert into public.ares_opportunities"
                "(tenant_id,deal_id,opportunity_type,state,opened_at,updated_at) "
                "values(%s,%s,'sentinel_config_test','detected',%s,%s) returning id",
                (
                    TENANT_ID,
                    deal_id,
                    datetime(2000, 1, 1, tzinfo=UTC),
                    datetime(2000, 1, 2, tzinfo=UTC),
                ),
            ).fetchone()[0]

        for kind in ("unassigned", "stale"):
            created = service.save_rule_sync(
                TENANT_ID,
                actor,
                SentinelRuleCommand(
                    title=f"Synthetic {kind}",
                    kind=kind,
                    threshold_hours=24,
                    enabled=True,
                    interval_minutes=60,
                    start_time_local=time(8, 0),
                    reason="Verify configured rule execution",
                ),
            )
            rule_ids.append(created["rule_id"])
        catalog = service.catalog_sync(TENANT_ID)
        assert all(
            any(item["rule_id"] == rule_id and item["can_run"] for item in catalog["items"])
            for rule_id in rule_ids
        )
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "update public.sentinel_schedules set next_run_at=now()-interval '1 second' "
                "where tenant_id=%s and rule_id=any(%s)",
                (TENANT_ID, rule_ids),
            )
        service.scan_sync()
        items = service.list_sync(TENANT_ID, limit=50)["items"]
        found_rule_ids = {
            item["rule_id"] for item in items if item["opportunity_id"] == opportunity_id
        }
        assert found_rule_ids >= set(rule_ids)
        stale_rule = next(item for item in catalog["items"] if item["kind"] == "stale")
        paused = service.save_rule_sync(
            TENANT_ID,
            actor,
            SentinelRuleCommand(
                expected_version=stale_rule["version"],
                title=stale_rule["title"],
                kind="stale",
                threshold_hours=24,
                enabled=False,
                interval_minutes=60,
                start_time_local=time(8, 0),
                reason="Pause synthetic rule",
            ),
            stale_rule["rule_id"],
        )
        assert paused["can_run"] is False
        assert not any(
            item["rule_id"] == stale_rule["rule_id"]
            for item in service.list_sync(TENANT_ID, limit=50)["items"]
        )
        service.archive_rule_sync(
            TENANT_ID,
            actor,
            stale_rule["rule_id"],
            paused["version"],
            "Archive synthetic rule",
        )
        assert not any(
            item["rule_id"] == stale_rule["rule_id"]
            for item in service.catalog_sync(TENANT_ID)["items"]
        )
        with psycopg.connect(DATABASE_URL) as connection:
            count = connection.execute(
                "select count(*) from public.sentinel_schedule_audit "
                "where tenant_id=%s and rule_id=any(%s) and actor_user_id=%s",
                (TENANT_ID, rule_ids, actor),
            ).fetchone()[0]
            assert count == 4
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                "delete from public.sentinel_findings where tenant_id=%s and rule_id=any(%s)",
                (TENANT_ID, rule_ids),
            )
            connection.execute(
                "delete from public.sentinel_scan_runs where tenant_id=%s and rule_id=any(%s)",
                (TENANT_ID, rule_ids),
            )
            connection.execute(
                "delete from public.sentinel_schedule_audit where tenant_id=%s and rule_id=any(%s)",
                (TENANT_ID, rule_ids),
            )
            connection.execute(
                "delete from public.sentinel_schedules where tenant_id=%s and rule_id=any(%s)",
                (TENANT_ID, rule_ids),
            )
            if opportunity_id is not None:
                connection.execute(
                    "delete from public.ares_opportunities where tenant_id=%s and id=%s",
                    (TENANT_ID, opportunity_id),
                )
            if deal_id is not None:
                connection.execute(
                    "delete from public.deals where tenant_id=%s and id=%s",
                    (TENANT_ID, deal_id),
                )
            connection.execute(
                "update public.tenant_quotas set sentinel_slots=%s where tenant_id=%s",
                (prior_slots[0], TENANT_ID),
            )
