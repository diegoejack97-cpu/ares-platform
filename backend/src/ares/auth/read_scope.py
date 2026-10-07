"""Apply database RLS to interactive reads, using the verified server principal.

Workers deliberately omit a reader. HTTP handlers must supply one: PostgreSQL
then revalidates membership, plan and ownership instead of trusting a cached role.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from ares.auth.models import AuthenticatedUser


@contextmanager
def read_connection(
    database_url: str, reader: AuthenticatedUser | None = None
) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        idle = connection.info.transaction_status == TransactionStatus.IDLE
        # The savepoint also restores claims/role on injected test connections.
        with connection.transaction(force_rollback=True):
            if idle:
                connection.execute("set transaction isolation level repeatable read, read only")
            connection.execute("set local statement_timeout='5s'")
            if reader is not None:
                connection.execute(
                    "select set_config('request.jwt.claims', %s, true)",
                    (
                        json.dumps(
                            {
                                "sub": str(reader.user_id),
                                "role": "authenticated",
                                "app_metadata": {"active_tenant_id": str(reader.tenant_id)},
                            }
                        ),
                    ),
                )
                connection.execute("set local role authenticated")
            yield connection
