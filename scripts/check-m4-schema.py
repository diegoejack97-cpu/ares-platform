"""Validate migration SQL from stdin against local Postgres, always rolling back."""

import sys

import psycopg

from ares.config import get_settings

settings = get_settings()
if settings.environment != "development":
    raise SystemExit("Local development only")
with psycopg.connect(settings.database_url, connect_timeout=5) as connection:
    before = connection.execute(
        "select count(*) from public.ares_opportunities"
    ).fetchone()
    connection.execute(sys.stdin.read(), prepare=False)
    connection.rollback()
    after = connection.execute(
        "select count(*) from public.ares_opportunities"
    ).fetchone()
    assert before == after
    print(f"M4_SCHEMA_VALIDATED_ROLLBACK preserved_opportunities={after}")
