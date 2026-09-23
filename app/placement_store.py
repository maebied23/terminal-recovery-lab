"""Revision-scoped immutable placement evidence and atomic outbox approval."""

import logging
import uuid
from psycopg.types.json import Jsonb
from .domain import RuleError
from .placement import guard, compare
from .store import ROOT

LOG = logging.getLogger("terminal.placement")


def create(store, run, revision, job_id):
    # Read SQL facts and snapshot under the same run lock. Release before simulation.
    with store.connect() as c:
        s = store.read(run, c, lock=True)
        if s["revision"] != revision:
            raise RuleError("State changed; refresh before comparing placement")
        guard(s, job_id)
        facts = c.execute(
            (ROOT / "sql/placement_candidates.sql").read_text(),
            dict(run=run, job=job_id),
        ).fetchall()
    result = compare(s, job_id, facts)
    id = str(uuid.uuid4())
    result["id"] = id
    with store.connect() as c:
        current = store.read(run, c, lock=True)
        if current["revision"] != revision:
            raise RuleError("State changed during placement comparison; compare again")
        guard(current, job_id)
        if s.get("movement"):
            for candidate in result["candidates"]:
                if candidate["validation"] != "passed":
                    continue
                profile = c.execute(
                    (ROOT / "sql/placement_temporal.sql").read_text(),
                    dict(
                        run=run,
                        rows=Jsonb(candidate["rows"]),
                        minute=s["minute"],
                        horizon=result["end_minute"],
                    ),
                ).fetchall()
                if any(p["occupied"] < 0 or p["free_slots"] < 0 for p in profile):
                    raise RuleError("SQL occupancy and physical replay disagree")
                candidate["occupancy"] = [
                    dict(
                        p, occupied=int(p["occupied"]), free_slots=int(p["free_slots"])
                    )
                    for p in profile
                    if p["location_id"] == candidate["destination"]
                ]
        c.execute(
            "INSERT INTO placement_proposals(id,run_id,job_id,base_revision,snapshot,result) VALUES(%s,%s,%s,%s,%s,%s)",
            (id, run, job_id, revision, Jsonb(s), Jsonb(result)),
        )
    LOG.info(
        "placement_compared id=%s run=%s revision=%s alternatives=%s",
        id,
        run,
        revision,
        len(result["candidates"]),
    )
    return result


def listing(store, run, job_id):
    with store.connect() as c:
        return c.execute(
            "SELECT id,base_revision,result,approved_destination,created_at FROM placement_proposals WHERE run_id=%s AND job_id=%s ORDER BY created_at DESC LIMIT 8",
            (run, job_id),
        ).fetchall()


def approval(c, run, s, proposal_id, destination, command_id):
    p = c.execute(
        "SELECT * FROM placement_proposals WHERE run_id=%s AND id=%s FOR UPDATE",
        (run, proposal_id),
    ).fetchone()
    if not p or p["base_revision"] != s["revision"] or p["approved_command"]:
        raise RuleError("Placement is missing, stale or already applied")
    guard(s, p["job_id"])
    candidate = next(
        (x for x in p["result"]["candidates"] if x["destination"] == destination), None
    )
    if not candidate or candidate["validation"] != "passed" or candidate["prescribed"]:
        raise RuleError("Choose a validated alternative destination")
    c.execute(
        "UPDATE placement_proposals SET approved_command=%s,approved_destination=%s WHERE id=%s",
        (command_id, destination, proposal_id),
    )
    return p["result"]
