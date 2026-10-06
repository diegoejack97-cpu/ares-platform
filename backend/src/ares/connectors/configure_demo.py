"""Create the explicitly configured HTTP connection only for a labeled demo company."""

import argparse

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ares.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-synthetic", action="store_true", required=True)
    parser.parse_args()
    settings = get_settings()
    if settings.environment != "demonstration":
        raise SystemExit("This command is restricted to demonstration")
    config = settings.crm_connections.get(settings.tenant_id)
    if config is None:
        raise SystemExit("An explicit company connection is required")
    with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
        tenant = db.execute(
            "select name from public.tenants where id=%s for update", (settings.tenant_id,)
        ).fetchone()
        if not tenant or not tenant["name"].startswith("[DEMO]"):
            raise SystemExit("Refusing a company without the [DEMO] label")
        owner = db.execute("select user_id from private.provider_operators where active").fetchone()
        if owner is None:
            raise SystemExit("Configure the separate platform owner before the demo connection")
        prior = db.execute(
            "select id,status from public.connections "
            "where tenant_id=%s and provider='fake-crm-http'",
            (settings.tenant_id,),
        ).fetchone()
        if prior:
            if prior["id"] != config.connection_id or prior["status"] == "revoked":
                raise SystemExit("Refusing to overwrite a different or revoked connection")
            print("The labeled demo connection is already configured")
            return
        db.execute(
            "insert into public.connections(id,tenant_id,provider,status) "
            "values(%s,%s,'fake-crm-http','configured')",
            (config.connection_id, settings.tenant_id),
        )
        db.execute(
            "insert into public.provider_audit"
            "(actor_id,tenant_id,action,after_state,reason) "
            "values(%s,%s,'demo.connection.configured',%s,'Explicit synthetic presentation setup')",
            (
                owner["user_id"],
                settings.tenant_id,
                Jsonb(
                    {
                        "connection_id": str(config.connection_id),
                        "provider": "fake-crm-http",
                        "synthetic": True,
                    }
                ),
            ),
        )
    print("Labeled demo connection configured; credentials remain server-only")


if __name__ == "__main__":
    main()
