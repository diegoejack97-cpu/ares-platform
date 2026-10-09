"""Rebuild derived relationships from existing Journal records; never changes CRM data."""

import psycopg
from psycopg.rows import dict_row

from ares.config import get_settings
from ares.graph.projector import project_opportunity


def main() -> None:
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as db:
        opportunities = db.execute(
            "select tenant_id,id from public.ares_opportunities order by tenant_id,id"
        ).fetchall()
        for opportunity in opportunities:
            project_opportunity(db, opportunity["tenant_id"], opportunity["id"])
    print(f"Rebuilt {len(opportunities)} opportunities from the Event Journal.")


if __name__ == "__main__":
    main()
