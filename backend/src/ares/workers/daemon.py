"""Supervised consumer for durable jobs, independent of API requests."""

import logging
import signal
import time
from threading import Event
from types import FrameType

from ares.config import get_settings
from ares.workers.tick import TickWorker


def main() -> None:
    settings = get_settings()
    stop = Event()

    def shutdown(_signal: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    worker = TickWorker(
        settings.database_url,
        settings.supabase_url,
        settings.supabase_secret_key.get_secret_value(),
        worker_name="ares-worker",
    )
    next_scan = 0.0
    while not stop.is_set():
        scan = time.monotonic() >= next_scan
        try:
            result = worker.run_once(scan_sentinels=scan)
            if scan and result.acquired:
                next_scan = time.monotonic() + 10
            if result.claimed or result.sentinel_findings:
                logging.info(
                    "tick claimed=%d succeeded=%d failed=%d findings=%d",
                    result.claimed,
                    result.succeeded,
                    result.failed,
                    result.sentinel_findings,
                )
        except Exception as error:
            logging.error("worker_tick_failed type=%s", type(error).__name__)
        stop.wait(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
