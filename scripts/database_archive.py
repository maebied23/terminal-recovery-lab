"""Consistent PostgreSQL backup and isolated restore verification.

Uses DATABASE_URL (or local generated credentials). Archives contain operational
history: keep them in ignored .local/, never publish them.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.store import Store, ROOT


def fingerprint(c):
    tables = [
        r[0]
        for r in c.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
    ]
    result = {}
    for table in tables:
        # Exact order-independent table content, including custody and history.
        rows = c.execute(
            sql.SQL("SELECT row_to_json(t)::text FROM {} t").format(
                sql.Identifier(table)
            )
        ).fetchall()
        values = sorted(
            json.dumps(json.loads(r[0]), sort_keys=True, separators=(",", ":"))
            for r in rows
        )
        result[table] = dict(
            rows=len(values),
            sha256=hashlib.sha256("\n".join(values).encode()).hexdigest(),
        )
    return result


def pg_env(dsn):
    params = conninfo_to_dict(dsn)
    env = os.environ.copy()
    for key, name in [
        ("host", "PGHOST"),
        ("port", "PGPORT"),
        ("user", "PGUSER"),
        ("password", "PGPASSWORD"),
        ("dbname", "PGDATABASE"),
        ("sslmode", "PGSSLMODE"),
    ]:
        if key in params:
            env[name] = params[key]
    return env


def run_pg(binary, args, dsn):
    directory = os.environ.get("PG_BIN", "")
    executable = str(Path(directory) / binary) if directory else binary
    subprocess.run(
        [executable, *args], env=pg_env(dsn), check=True, stdout=subprocess.DEVNULL
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["backup", "verify-restore"])
    p.add_argument("archive", type=Path)
    args = p.parse_args()
    dsn = Store().dsn
    sidecar = args.archive.with_suffix(args.archive.suffix + ".json")
    if args.action == "backup":
        if args.archive.exists() or sidecar.exists():
            raise SystemExit(
                "Choose a new archive path; existing backups are never overwritten"
            )
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        with psycopg.connect(dsn) as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            snapshot = c.execute("SELECT pg_export_snapshot()").fetchone()[0]
            expected = fingerprint(c)
            run_pg(
                "pg_dump",
                [
                    "--format=custom",
                    "--no-owner",
                    "--snapshot=" + snapshot,
                    "--file=" + str(args.archive),
                ],
                dsn,
            )
        args.archive.chmod(0o600)
        sidecar.write_text(json.dumps(expected, indent=2) + "\n")
        sidecar.chmod(0o600)
        print(
            json.dumps(
                dict(
                    status="backed up",
                    tables=len(expected),
                    rows=sum(t["rows"] for t in expected.values()),
                )
            )
        )
    else:
        expected = json.loads(sidecar.read_text())
        target = "terminal_restore_" + uuid.uuid4().hex[:12]
        params = conninfo_to_dict(dsn)
        params["dbname"] = "postgres"
        admin_dsn = make_conninfo(**params)
        with psycopg.connect(admin_dsn, autocommit=True) as c:
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
        params["dbname"] = target
        target_dsn = make_conninfo(**params)
        try:
            run_pg(
                "pg_restore",
                [
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "--dbname=" + target,
                    str(args.archive),
                ],
                target_dsn,
            )
            with psycopg.connect(target_dsn) as c:
                actual = fingerprint(c)
            if actual != expected:
                raise RuntimeError(
                    "Restored contents differ from the exported snapshot"
                )
            print(
                json.dumps(
                    dict(
                        status="restore verified",
                        tables=len(actual),
                        rows=sum(t["rows"] for t in actual.values()),
                    )
                )
            )
        finally:
            with psycopg.connect(admin_dsn, autocommit=True) as c:
                c.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target)))


if __name__ == "__main__":
    main()
