"""Healthcheck for the supervised worker; no credentials or row payloads are emitted."""

import psycopg

from ares.config import Settings, get_settings


def worker_ready(settings: Settings) -> bool:
    try:
        with psycopg.connect(settings.database_url, connect_timeout=3) as db:
            db.execute("set local statement_timeout='3s'")
            row = db.execute(
                "select exists(select 1 from public.worker_ticks where worker_name='ares-worker' "
                "and acquired "
                "and finished_at>clock_timestamp()-make_interval(secs=>%s))",
                (settings.worker_stale_seconds,),
            ).fetchone()
        return bool(row and row[0])
    except psycopg.Error:
        return False


if __name__ == "__main__":
    raise SystemExit(0 if worker_ready(get_settings()) else 1)
