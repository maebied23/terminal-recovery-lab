"""Transactional relational current state, immutable evidence, durable command outbox."""

import os, json, uuid, logging
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .domain import seed_state, transition, RuleError

LOG = logging.getLogger("terminal.store")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DSN = "postgresql://terminal_lab@127.0.0.1:55432/terminal_lab"
TABLES = {
    "locations": ("locations", ["id", "kind", "capacity"]),
    "equipment": ("equipment", ["id", "kind", "status"]),
    "commitments": ("commitments", ["id", "location_id", "cutoff", "kind"]),
    "containers": ("containers", ["id", "visit_id", "location_id", "commitment_id"]),
    "jobs": (
        "move_jobs",
        [
            "id",
            "container_id",
            "source_id",
            "target_id",
            "equipment_id",
            "status",
            "visit_id",
        ],
    ),
}


class Store:
    def __init__(self, dsn=None):
        local = ROOT / ".local/database-url"
        self.dsn = (
            dsn
            or os.getenv("DATABASE_URL")
            or (local.read_text().strip() if local.exists() else DEFAULT_DSN)
        )

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5)

    def initialize(self):
        with self.connect() as c:
            # Serialize schema ownership and never replay already applied DDL
            # against live readers. Repeated ALTERs previously risked deadlock.
            c.execute("SELECT pg_advisory_xact_lock(790024310)")
            c.execute(
                "CREATE TABLE IF NOT EXISTS schema_version(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            applied = {
                r["version"]
                for r in c.execute("SELECT version FROM schema_version").fetchall()
            }
            for migration in sorted((ROOT / "migrations").glob("*.sql")):
                version = int(migration.name.split("_")[0])
                if version not in applied:
                    c.execute(migration.read_text())
                    c.execute(
                        "INSERT INTO schema_version(version) VALUES(%s) ON CONFLICT DO NOTHING",
                        (version,),
                    )
            if not c.execute("SELECT id FROM runs LIMIT 1").fetchone():
                self.create_run(c, "main", "Northstar · morning shift", seed_state())

    def create_run(self, c, id, name, state):
        c.execute(
            "INSERT INTO runs(id,name,metadata) VALUES(%s,%s,%s)", (id, name, Jsonb({}))
        )
        self.persist(c, id, state, [], None)

    def persist(self, c, run, s, events, command):
        visits = {cargo["id"]: cargo["visit_id"] for cargo in s["containers"]}
        for job in s["jobs"]:
            if (
                job.get("visit_id", visits[job["container_id"]])
                != visits[job["container_id"]]
            ):
                raise RuleError(
                    "Work order does not belong to the container's current visit"
                )
            job["visit_id"] = visits[job["container_id"]]
        meta = {
            k: v
            for k, v in s.items()
            if k not in (*TABLES, "revision", "minute", "observations")
        }
        c.execute(
            "UPDATE runs SET revision=%s,minute=%s,metadata=%s WHERE id=%s",
            (s["revision"], s["minute"], Jsonb(meta), run),
        )
        for key, (table, columns) in TABLES.items():
            names = ["run_id"] + columns + ["attributes"]
            query = (
                f'INSERT INTO {table} ({",".join(names)}) VALUES ({",".join(["%s"]*len(names))}) ON CONFLICT(run_id,id) DO UPDATE SET '
                + ",".join(
                    f"{n}=EXCLUDED.{n}" for n in names if n not in ("run_id", "id")
                )
            )
            values = []
            for row in s[key]:
                attrs = {
                    k: v
                    for k, v in row.items()
                    if k not in columns and k != "dependencies"
                }
                values.append([run] + [row[k] for k in columns] + [Jsonb(attrs)])
            with c.cursor() as cur:
                cur.executemany(query, values)
        for cargo in s["containers"]:
            c.execute(
                "INSERT INTO cargo_visits VALUES(%s,%s,%s,%s) ON CONFLICT(run_id,id) DO UPDATE SET commitment_id=EXCLUDED.commitment_id",
                (run, cargo["visit_id"], cargo["id"], cargo["commitment_id"]),
            )
        c.execute("DELETE FROM job_dependencies WHERE run_id=%s", (run,))
        from .relationships import dependency_detail
        from .domain import by_id

        for j in s["jobs"]:
            for d in j["dependencies"]:
                c.execute(
                    "INSERT INTO job_dependencies(run_id,job_id,predecessor_id,details) VALUES(%s,%s,%s,%s)",
                    (
                        run,
                        j["id"],
                        d,
                        Jsonb(dependency_detail(s, j, by_id(s["jobs"], d))),
                    ),
                )
        for o in s["observations"]:
            c.execute(
                "INSERT INTO observations(run_id,entity_id,valid_minute,recorded_minute,revision,value,source,supersedes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    run,
                    o["entity_id"],
                    o["valid_minute"],
                    o["recorded_minute"],
                    o["revision"],
                    o["value"],
                    o["source"],
                    o["supersedes"],
                ),
            )
        from .movement_store import persist as persist_movement

        persist_movement(c, run, s)
        from .schedule_store import sync

        sync(c, run, s)
        for e in events:
            c.execute(
                "INSERT INTO events(run_id,revision,kind,entity_id,valid_minute,command_id,source,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    run,
                    s["revision"],
                    e["kind"],
                    e["entity_id"],
                    e.get("valid_minute", s["minute"]),
                    command,
                    e.get("source", "simulator"),
                    Jsonb(e),
                ),
            )
        c.execute(
            "INSERT INTO snapshots(run_id,revision,minute,state) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (run, s["revision"], s["minute"], Jsonb(s)),
        )

    def read(self, run="main", c=None, lock=False):
        if c is None:
            with self.connect() as conn:
                conn.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                return self.read(run, conn)
        row = c.execute(
            "SELECT * FROM runs WHERE id=%s" + (" FOR UPDATE" if lock else ""), (run,)
        ).fetchone()
        if not row:
            raise RuleError("Run not found")
        s = dict(row["metadata"], revision=row["revision"], minute=row["minute"])
        for key, (table, columns) in TABLES.items():
            rows = c.execute(
                f"SELECT * FROM {table} WHERE run_id=%s ORDER BY id", (run,)
            ).fetchall()
            s[key] = [dict(r["attributes"], **{k: r[k] for k in columns}) for r in rows]
        deps = c.execute(
            "SELECT job_id,predecessor_id,details FROM job_dependencies WHERE run_id=%s",
            (run,),
        ).fetchall()
        for j in s["jobs"]:
            j["dependencies"] = [
                d["predecessor_id"] for d in deps if d["job_id"] == j["id"]
            ]
            j["dependency_details"] = {
                d["predecessor_id"]: d["details"]
                for d in deps
                if d["job_id"] == j["id"] and d["details"]
            }
        s["observations"] = c.execute(
            "SELECT entity_id,valid_minute,recorded_minute,revision,value,source,supersedes FROM observations WHERE run_id=%s ORDER BY revision,id",
            (run,),
        ).fetchall()
        return s

    def enqueue(self, run, cmd, actor):
        payload = dict(cmd)
        id = payload.pop("command_id")
        revision = payload.pop("expected_revision")
        with self.connect() as c:
            # Same run lock orders concurrent submissions; unique key guards cross-run collisions.
            s = self.read(run, c, lock=True)
            old = c.execute("SELECT * FROM commands WHERE id=%s", (id,)).fetchone()
            if old:
                if (
                    old["payload"] != payload
                    or old["expected_revision"] != revision
                    or old["run_id"] != run
                    or old["actor"] != actor
                ):
                    raise RuleError("Idempotency key reused with different content")
                return old
            error = None
            if s["revision"] != revision and payload["action"] != "pause":
                error = "Stale revision. Refresh and retry."
            if payload["action"] == "approve_plan":
                plan = c.execute(
                    "SELECT * FROM plans WHERE id=%s AND run_id=%s",
                    (payload.get("plan_id"), run),
                ).fetchone()
                if (
                    not plan
                    or plan["base_revision"] != revision
                    or plan["status"] != "proposed"
                ):
                    error = (
                        "Plan is missing, stale, or already approved. Compare again."
                    )
            if payload["action"] == "approve_schedule":
                plan = c.execute(
                    "SELECT * FROM schedule_plans WHERE id=%s AND run_id=%s",
                    (payload.get("plan_id"), run),
                ).fetchone()
                if (
                    not plan
                    or plan["base_revision"] != revision
                    or plan["status"] != "proposed"
                    or s["running"]
                ):
                    error = "Schedule is stale, already approved, or the clock is running. Pause and compare again."
            c.execute(
                "INSERT INTO commands(id,run_id,actor,expected_revision,payload,status,result) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    id,
                    run,
                    actor,
                    revision,
                    Jsonb(payload),
                    "rejected" if error else "queued",
                    Jsonb({"error": error}) if error else None,
                ),
            )
            if not error:
                c.execute("INSERT INTO outbox(command_id) VALUES(%s)", (id,))
            return c.execute("SELECT * FROM commands WHERE id=%s", (id,)).fetchone()

    def process_one(self):
        with self.connect() as c:
            row = c.execute(
                "SELECT * FROM outbox WHERE status='queued' AND available_at<=now() ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if not row:
                return False
            cmd = c.execute(
                "SELECT * FROM commands WHERE id=%s", (row["command_id"],)
            ).fetchone()
            try:
                # Savepoint preserves a durable rejected command while rolling back partial writes.
                with c.transaction():
                    s = self.read(cmd["run_id"], c, lock=True)
                    if (
                        s["revision"] != cmd["expected_revision"]
                        and cmd["payload"]["action"] != "pause"
                    ):
                        raise RuleError(
                            "State changed before execution; command rejected"
                        )
                    payload = dict(cmd["payload"])
                    if payload["action"] == "approve_plan":
                        plan = c.execute(
                            "SELECT * FROM plans WHERE id=%s AND run_id=%s",
                            (payload["plan_id"], cmd["run_id"]),
                        ).fetchone()
                        if (
                            not plan
                            or plan["base_revision"] != s["revision"]
                            or plan["status"] != "proposed"
                        ):
                            raise RuleError("Plan is stale; compare again")
                        payload["policy"] = plan["policy"]
                        c.execute(
                            "UPDATE plans SET status='approved' WHERE id=%s",
                            (plan["id"],),
                        )
                    if payload["action"] == "approve_schedule":
                        from .schedule_store import approval

                        payload["schedule_plan"] = approval(
                            c, cmd["run_id"], s, payload["plan_id"], cmd["id"]
                        )
                    if payload["action"] == "approve_placement":
                        from .placement_store import approval as placement_approval

                        payload["placement"] = placement_approval(
                            c,
                            cmd["run_id"],
                            s,
                            payload["plan_id"],
                            payload["destination_id"],
                            cmd["id"],
                        )
                    from .feed import reconcile_due

                    next_state, events = transition(
                        s,
                        payload,
                        lambda current: reconcile_due(c, cmd["run_id"], current),
                    )
                    self.persist(c, cmd["run_id"], next_state, events, cmd["id"])
                    c.execute(
                        "UPDATE commands SET status='acknowledged',result=%s,updated_at=now() WHERE id=%s",
                        (
                            Jsonb(
                                {
                                    "revision": next_state["revision"],
                                    "message": "Applied to simulator; movement completion is tracked separately",
                                }
                            ),
                            cmd["id"],
                        ),
                    )
                    c.execute(
                        "UPDATE outbox SET status='delivered',attempts=attempts+1 WHERE id=%s",
                        (row["id"],),
                    )
                LOG.info(
                    "command_ack id=%s run=%s revision=%s",
                    cmd["id"],
                    cmd["run_id"],
                    next_state["revision"],
                )
            except RuleError as exc:
                c.execute(
                    "UPDATE commands SET status='rejected',result=%s,updated_at=now() WHERE id=%s",
                    (Jsonb({"error": str(exc)}), cmd["id"]),
                )
                c.execute(
                    "UPDATE outbox SET status='rejected',last_error=%s WHERE id=%s",
                    (str(exc), row["id"]),
                )
            except Exception as exc:
                LOG.exception("command_delivery_failed id=%s", cmd["id"])
                n = row["attempts"] + 1
                c.execute(
                    "UPDATE outbox SET attempts=%s,status=%s,last_error=%s,available_at=now()+(%s * interval '1 second') WHERE id=%s",
                    (
                        n,
                        "failed" if n >= 3 else "queued",
                        type(exc).__name__,
                        n * n,
                        row["id"],
                    ),
                )
                if n >= 3:
                    c.execute(
                        "UPDATE commands SET status='failed',result=%s WHERE id=%s",
                        (
                            Jsonb(
                                {
                                    "error": "Delivery failed after three attempts. Inspect server logs; no automatic reissue."
                                }
                            ),
                            cmd["id"],
                        ),
                    )
            return True

    def auto_tick(self):
        with self.connect() as c:
            rows = c.execute(
                "SELECT id FROM runs WHERE (metadata->>'running')::boolean=true FOR UPDATE SKIP LOCKED"
            ).fetchall()
            for row in rows:
                # Process explicit queued commands before advancing the clock.
                if c.execute(
                    "SELECT 1 FROM commands WHERE run_id=%s AND status='queued' LIMIT 1",
                    (row["id"],),
                ).fetchone():
                    continue
                s = self.read(row["id"], c)
                from .feed import reconcile_due

                ns, events = transition(
                    s,
                    dict(action="advance", minutes=s["speed"]),
                    lambda current: reconcile_due(c, row["id"], current),
                )
                if ns["minute"] >= 240:
                    ns["running"] = False
                    events.append(
                        dict(
                            kind="clock.auto_paused",
                            entity_id="terminal",
                            valid_minute=ns["minute"],
                            message="Finite demonstration shift paused after 240 minutes",
                        )
                    )
                self.persist(c, row["id"], ns, events, None)

    def list_rows(self, table, run=None, limit=100):
        if table not in (
            "events",
            "commands",
            "plans",
            "experiments",
            "runs",
            "source_assertions",
        ):
            raise ValueError("Unknown collection")
        with self.connect() as c:
            if run:
                return c.execute(
                    f"SELECT * FROM {table} WHERE run_id=%s ORDER BY "
                    + ("id DESC" if table == "events" else "created_at DESC")
                    + " LIMIT %s",
                    (run, limit),
                ).fetchall()
            return c.execute(f"SELECT * FROM {table} LIMIT %s", (limit,)).fetchall()

    def history(self, run, revision):
        with self.connect() as c:
            row = c.execute(
                "SELECT * FROM snapshots WHERE run_id=%s AND revision=%s",
                (run, revision),
            ).fetchone()
            if not row:
                raise RuleError("Historical revision not found")
            return row
