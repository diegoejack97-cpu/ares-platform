"""Local M4 queue pump; stopping it never loses durable jobs."""

import logging
import time

from ares.config import get_settings
from ares.workers.tick import TickWorker


def main() -> None:
    settings = get_settings()
    if settings.environment != "development":
        raise SystemExit("Local integration worker is development-only")
    worker = TickWorker(
        settings.database_url,
        settings.supabase_url,
        settings.supabase_secret_key.get_secret_value(),
        worker_name="ares-local-integrations",
    )
    sentinel_worker = TickWorker(
        settings.database_url,
        settings.supabase_url,
        settings.supabase_secret_key.get_secret_value(),
        worker_name="ares-local-sentinels",
    )
    next_sentinel_scan = 0.0
    while True:
        try:
            result = worker.run_once(job_kinds=["integration.sync", "integration.project"])
            if result.claimed:
                print(
                    f"integration_tick claimed={result.claimed} failed={result.failed}", flush=True
                )
        except Exception as error:
            logging.warning("integration_worker_unavailable: %s", type(error).__name__)
        if time.monotonic() >= next_sentinel_scan:
            try:
                sentinel_worker.run_once(job_kinds=[], scan_sentinels=True)
            except Exception as error:
                logging.warning("sentinel_worker_unavailable: %s", type(error).__name__)
            next_sentinel_scan = time.monotonic() + 60
        time.sleep(5)


if __name__ == "__main__":
    main()
