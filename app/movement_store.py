"""Typed read projections committed with the authoritative revision and snapshot."""

from psycopg.types.json import Jsonb
from psycopg.types.range import Range
from .domain import by_id


def persist(c, run, s):
    if not s.get("movement"):
        return
    net = s["movement"]
    for n in net["nodes"]:
        c.execute(
            "INSERT INTO transport_nodes VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (run, n["id"], n["x"], n["y"]),
        )
    for e in net["edges"]:
        c.execute(
            "INSERT INTO transport_edges VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(run_id,id) DO UPDATE SET closed=EXCLUDED.closed",
            (
                run,
                e["id"],
                e["source"],
                e["target"],
                e["metres"],
                e["loaded_mpm"],
                e["empty_mpm"],
                e.get("closed", False),
                Jsonb(e["compatible"]),
                net["digest"],
            ),
        )
    for cargo in s["containers"]:
        owner = cargo["custody"]
        c.execute(
            "INSERT INTO cargo_custody VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(run_id,container_id) DO UPDATE SET location_id=EXCLUDED.location_id,equipment_id=EXCLUDED.equipment_id,job_id=EXCLUDED.job_id,revision=EXCLUDED.revision",
            (
                run,
                cargo["id"],
                owner["id"] if owner["kind"] == "location" else None,
                owner["id"] if owner["kind"] == "equipment" else None,
                cargo["job_id"],
                s["revision"],
            ),
        )


def approve(c, run, plan_id, rows):
    c.execute(
        "UPDATE stage_reservations SET active=false WHERE run_id=%s AND active", (run,)
    )
    for r in rows:
        for i, p in enumerate(r["stages"]):
            for eid in p["resources"]:
                c.execute(
                    "INSERT INTO stage_reservations VALUES(%s,%s,%s,%s,%s,%s,true)",
                    (
                        plan_id,
                        run,
                        r["job_id"],
                        i,
                        eid,
                        Range(p["start"], p["end"], "[)"),
                    ),
                )


def sync(c, run, s):
    plan = s.get("schedule")
    c.execute(
        "UPDATE stage_reservations SET active=false WHERE run_id=%s AND active", (run,)
    )
    if not plan:
        return
    active = plan["status"] in ("approved", "executing")
    for r in plan["rows"]:
        j = by_id(s["jobs"], r["job_id"])
        for i, p in enumerate(r["stages"]):
            for eid in p["resources"]:
                owning = j["status"] == "running" and eid in j["resources"]
                # Actual ownership lives independently in equipment/custody. Extend only
                # the current interval, never every past use of the same machine.
                actual_kind = j.get("movement_stages", [{}])[
                    j.get("stage_index", 0)
                ].get("kind")
                current = owning and p.get("kind") == actual_kind
                keep = (
                    active and j["status"] != "completed" and p["end"] > s["minute"]
                ) or current
                end = max(p["end"], s["minute"] + 1) if current else p["end"]
                c.execute(
                    "UPDATE stage_reservations SET active=%s,occupied=%s WHERE plan_id=%s AND job_id=%s AND ordinal=%s AND equipment_id=%s",
                    (
                        keep,
                        Range(p["start"], end, "[)"),
                        plan["id"],
                        r["job_id"],
                        i,
                        eid,
                    ),
                )
