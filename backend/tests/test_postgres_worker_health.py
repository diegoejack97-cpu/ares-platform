import os

import psycopg
import pytest

from ares.config import Settings
from ares.workers.health import worker_ready
from ares.workers.tick import TickWorker

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("ARES_TEST_DATABASE_URL"), reason="isolated PostgreSQL required"
    ),
]


def test_worker_readiness_requires_a_recent_completed_tick():
    url = os.environ["ARES_TEST_DATABASE_URL"]
    settings = Settings(_env_file=None, database_url=url, worker_stale_seconds=30)
    worker = TickWorker(url, "", "", worker_name="ares-worker")
    worker.run_once(batch_size=0, job_kinds=[], scan_sentinels=False)
    assert worker_ready(settings)
    with psycopg.connect(url) as db:
        db.execute("update public.worker_ticks set acquired=false where worker_name='ares-worker'")
    assert not worker_ready(settings)
    worker.run_once(batch_size=0, job_kinds=[], scan_sentinels=False)
    assert worker_ready(settings)
    with psycopg.connect(url) as db:
        db.execute(
            "update public.worker_ticks set finished_at=now()-interval '10 minutes' "
            "where worker_name='ares-worker'"
        )
    assert not worker_ready(settings)
