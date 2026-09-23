"""Durable bounded planning jobs and transactional reservation projection."""

import logging
import uuid
from psycopg.types.json import Jsonb
from psycopg.types.range import Range
from .domain import RuleError, by_id
from .scheduling import build

LOG = logging.getLogger("terminal.schedules")


def enqueue(store, run, revision, focus, horizon=180):
    with store.connect() as c:
        s = store.read(run, c, lock=True)
        if s["revision"] != revision or s["running"]:
            raise RuleError("Pause at the current revision before building schedules")
        if not by_id(s["commitments"], focus):
            raise RuleError("Select a departure in this run")
        if c.execute(
            "SELECT 1 FROM schedule_requests WHERE run_id=%s AND status IN ('queued','running')",
            (run,),
        ).fetchone():
            raise RuleError("A schedule comparison is already queued or running")
        id = str(uuid.uuid4())
        c.execute(
            "INSERT INTO schedule_requests(id,run_id,base_revision,snapshot,horizon,focus_commitment) VALUES(%s,%s,%s,%s,%s,%s)",
            (id, run, revision, Jsonb(s), horizon, focus),
        )
        return id


def work(store):
    with store.connect() as c:
        request = c.execute(
            "SELECT * FROM schedule_requests WHERE status='queued' OR (status='running' AND lease_until<now()) ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
        ).fetchone()
        if not request:
            return False
        attempt = request["attempts"] + 1
        if attempt > 3:
            c.execute(
                "UPDATE schedule_requests SET status='failed',error='Planner lease expired three times' WHERE id=%s",
                (request["id"],),
            )
            return True
        c.execute(
            "UPDATE schedule_requests SET status='running',attempts=%s,lease_until=now()+interval '90 seconds' WHERE id=%s",
            (attempt, request["id"]),
        )
    try:
        result = build(request["snapshot"], request["horizon"])
        with store.connect() as c:
            owned = c.execute(
                "SELECT id FROM schedule_requests WHERE id=%s AND status='running' AND attempts=%s FOR UPDATE",
                (request["id"], attempt),
            ).fetchone()
            if not owned:
                return True
            for candidate in result["candidates"]:
                if candidate["validation"] != "passed":
                    continue
                candidate["plan_id"] = str(uuid.uuid4())
                c.execute(
                    "INSERT INTO schedule_plans(id,request_id,run_id,base_revision,candidate,end_minute) VALUES(%s,%s,%s,%s,%s,%s)",
                    (
                        candidate["plan_id"],
                        request["id"],
                        request["run_id"],
                        request["base_revision"],
                        Jsonb(candidate),
                        result["end_minute"],
                    ),
                )
            c.execute(
                "UPDATE schedule_requests SET status='completed',result=%s,lease_until=NULL WHERE id=%s",
                (Jsonb(result), request["id"]),
            )
        LOG.info(
            "schedule_built request=%s run=%s revision=%s solver=%s",
            request["id"],
            request["run_id"],
            request["base_revision"],
            result["solver"]["status"],
        )
    except Exception as exc:
        LOG.exception("schedule_failed request=%s", request["id"])
        with store.connect() as c:
            c.execute(
                "UPDATE schedule_requests SET status='failed',error=%s,lease_until=NULL WHERE id=%s AND attempts=%s",
                (
                    (
                        str(exc)
                        if isinstance(exc, RuleError)
                        else "Planner failed; inspect server logs"
                    ),
                    request["id"],
                    attempt,
                ),
            )
    return True


def approval(c, run, s, plan_id, command_id):
    p = c.execute(
        "SELECT * FROM schedule_plans WHERE id=%s AND run_id=%s FOR UPDATE",
        (plan_id, run),
    ).fetchone()
    if not p or p["status"] != "proposed" or p["base_revision"] != s["revision"]:
        raise RuleError("Schedule is missing, stale or already approved; compare again")
    if s["running"]:
        raise RuleError("Pause before approving scheduled work")
    # Called inside the outbox savepoint. Replay failure rolls ALL these writes back.
    c.execute(
        "UPDATE schedule_plans SET status='superseded' WHERE run_id=%s AND status IN ('approved','executing','interrupted','withdrawn')",
        (run,),
    )
    c.execute(
        "UPDATE equipment_reservations SET active=false WHERE run_id=%s AND active",
        (run,),
    )
    c.execute(
        "UPDATE schedule_plans SET status='approved',approved_command=%s WHERE id=%s",
        (command_id, plan_id),
    )
    for r in p["candidate"]["rows"]:
        for i, stage in enumerate(r["stages"]):
            c.execute(
                "INSERT INTO schedule_stages VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    plan_id,
                    run,
                    r["job_id"],
                    i,
                    stage["name"],
                    stage["start"],
                    stage["end"],
                ),
            )
        for eid in [] if s.get("movement") else r["resources"]:
            c.execute(
                "INSERT INTO equipment_reservations(plan_id,run_id,job_id,equipment_id,occupied) VALUES(%s,%s,%s,%s,%s)",
                (plan_id, run, r["job_id"], eid, Range(r["start"], r["end"], "[)")),
            )
    if s.get("movement"):
        from .movement_store import approve

        approve(c, run, plan_id, p["candidate"]["rows"])
    return dict(
        id=plan_id,
        base_revision=p["base_revision"],
        end_minute=p["end_minute"],
        title=p["candidate"]["title"],
        rows=p["candidate"]["rows"],
        projection=p["candidate"]["services"],
        metrics=p["candidate"]["metrics"],
    )


def sync(c, run, s):
    """Current bookings and immutable state snapshot change in the same transaction.

    Interrupted plans release future bookings, but never release an in-progress load.
    Overruns extend the running reservation on each clock tick until completion.
    """
    if s.get("movement"):
        from .movement_store import sync as stage_sync

        stage_sync(c, run, s)
        if s.get("schedule"):
            c.execute(
                "UPDATE schedule_plans SET status=%s WHERE run_id=%s AND id=%s",
                (s["schedule"]["status"], run, s["schedule"]["id"]),
            )
        return
    plan = s.get("schedule")
    if not plan:
        c.execute(
            "UPDATE equipment_reservations SET active=false WHERE run_id=%s AND active",
            (run,),
        )
        return
    c.execute(
        "UPDATE schedule_plans SET status=%s WHERE run_id=%s AND id=%s",
        (plan["status"], run, plan["id"]),
    )
    # Clear pending conflicts before extending frozen bookings after an interruption.
    if plan["status"] in ("interrupted", "withdrawn", "completed"):
        c.execute(
            "UPDATE equipment_reservations SET active=false WHERE run_id=%s AND plan_id=%s",
            (run, plan["id"]),
        )
    for r in plan["rows"]:
        j = by_id(s["jobs"], r["job_id"])
        active = (
            j["status"] == "running"
            or j["status"] == "queued"
            and plan["status"] in ("approved", "executing")
        )
        # Use a finite domain limit for the local shift, extending on every tick.
        end = max(r["end"], s["minute"] + 1) if j["status"] == "running" else r["end"]
        c.execute(
            "UPDATE equipment_reservations SET active=%s,occupied=%s WHERE run_id=%s AND plan_id=%s AND job_id=%s",
            (active, Range(r["start"], end, "[)"), run, plan["id"], r["job_id"]),
        )


def listing(store, run):
    with store.connect() as c:
        return c.execute(
            "SELECT id,base_revision,focus_commitment,status,result,error,created_at FROM schedule_requests WHERE run_id=%s ORDER BY created_at DESC LIMIT 12",
            (run,),
        ).fetchall()


def feedback(store, run):
    from .store import ROOT

    with store.connect() as c:
        return c.execute(
            (ROOT / "sql/schedule_feedback.sql").read_text(), {"run": run}
        ).fetchall()
