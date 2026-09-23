"""Read-only departure decisions: relational scope, shared feasibility rules, evidence.

No optimizer, generated confidence or automatic work reconciliation lives here.
"""

from pathlib import Path
from psycopg.types.json import Jsonb
from .domain import RuleError, blockers, requirements, by_id

SQL = Path(__file__).resolve().parents[1] / "sql"
DEPENDENCIES = (SQL / "diagnosis_dependencies.sql").read_text()
SUMMARY = (SQL / "diagnosis_summary.sql").read_text()
CALENDAR = (SQL / "diagnosis_calendar.sql").read_text()
RULES = {
    "Predecessor move incomplete": (
        "precedence",
        "R-STACK",
        "Inspect prerequisite work",
        "Work & commitments",
    ),
    "Cargo not at planned pickup": (
        "position",
        "R-POSITION",
        "Review instruction and position evidence",
        "Evidence",
    ),
    "Outbound authority hold": (
        "authority",
        "R-AUTHORITY",
        "Confirm release with the authority owner",
        "Evidence",
    ),
    "Another container is stacked above": (
        "access",
        "R-STACK",
        "Review an access plan",
        "Recovery",
    ),
    "Outbound service not open": (
        "service",
        "R-SERVICE",
        "Check the published service window",
        "Work & commitments",
    ),
    "Outbound service closed": (
        "cutoff",
        "R-SERVICE",
        "Escalate the missed service; review remaining work",
        "Recovery",
    ),
    "Vessel not alongside": (
        "service",
        "R-SERVICE",
        "Check the vessel service window",
        "Work & commitments",
    ),
    "Destination capacity reserved/full": (
        "capacity",
        "R-CAPACITY",
        "Inspect destination occupancy and incoming moves",
        "Work & commitments",
    ),
    "Equipment outside operating envelope": (
        "capability",
        "R-RESOURCE",
        "Review compatible handling equipment",
        "Recovery",
    ),
}


def job_issues(state, job, mismatch):
    """Explain the SAME checks dispatch uses, retaining concrete supporting facts."""
    cargo = by_id(state["containers"], job["container_id"])
    result = []
    for reason in blockers(state, job):
        code, rule, action, page = RULES.get(
            reason,
            (
                "equipment",
                "R-RESOURCE",
                "Review equipment availability and competing work",
                "Recovery",
            ),
        )
        facts = dict(
            job_id=job["id"],
            cargo_id=cargo["id"],
            location_id=cargo["location_id"],
            planned_pickup=job["source_id"],
            target_id=job["target_id"],
            equipment_id=job["equipment_id"],
        )
        if code == "precedence":
            facts["incomplete_predecessors"] = [
                d
                for d in job["dependencies"]
                if by_id(state["jobs"], d)["status"] != "completed"
            ]
        elif code == "position":
            code = "plan_mismatch" if mismatch else "awaiting_transfer"
            if not mismatch:
                action, page = (
                    "Follow the planned upstream delivery",
                    "Work & commitments",
                )
        elif code == "authority":
            facts.update(released=cargo["released"], hold_reason=cargo["hold_reason"])
        elif code == "access":
            facts["covering_cargo"] = [
                c["id"]
                for c in state["containers"]
                if c["location_id"] == cargo["location_id"]
                and c["tier"] > cargo["tier"]
            ]
        elif code == "capacity":
            facts.update(
                capacity=by_id(state["locations"], job["target_id"])["capacity"],
                occupants=[
                    c["id"]
                    for c in state["containers"]
                    if c["location_id"] == job["target_id"]
                ],
                incoming=[
                    j["id"]
                    for j in state["jobs"]
                    if j["status"] == "running" and j["target_id"] == job["target_id"]
                ],
            )
        elif code == "service" or code == "cutoff":
            co = by_id(state["commitments"], cargo["commitment_id"])
            if job["kind"] == "discharge":
                co = next(
                    (
                        x
                        for x in state["commitments"]
                        if x["location_id"] == job["source_id"]
                    ),
                    None,
                )
            facts["service"] = co
        elif code in ("equipment", "capability"):
            facts["requirements"] = requirements(state, job)
            facts["resources"] = [
                e
                for e in state["equipment"]
                if e["id"] == job["equipment_id"] or e["id"] in job.get("resources", [])
            ]
        entities = {cargo["id"], job["equipment_id"], *job.get("resources", [])}
        facts["accepted_observations"] = {
            k: v
            for k, v in state.get("input_provenance", {}).items()
            if k.split("/")[0] in entities
        }
        result.append(
            dict(
                code=code,
                reason=reason,
                rule=rule,
                action=action,
                page=page,
                facts=facts,
                requires_review=code == "plan_mismatch",
            )
        )
    return result


def describe_visit(state, row):
    """Pure diagnosis. SQL supplies membership and contradiction facts; rules supply guards."""
    jobs = {j["id"]: j for j in state["jobs"]}
    mismatches = {m["job_id"] for m in row["mismatches"]}
    visiting, seen, ordered, integrity = set(), set(), [], []

    def visit(id):
        if id in visiting:
            integrity.append(f"Dependency cycle at {id}")
            return
        if id in seen:
            return
        if id not in jobs:
            integrity.append(f"Missing work {id}")
            return
        visiting.add(id)
        for d in jobs[id]["dependencies"]:
            visit(d)
        visiting.remove(id)
        seen.add(id)
        ordered.append(id)

    for id in row["final_ids"]:
        visit(id)
    if len(row["final_ids"]) != 1:
        integrity.append(
            "Exactly one final delivery instruction is required for this visit"
        )
    details = []
    for id in ordered:
        j = jobs[id]
        # An integrity error must remain inspectable instead of crashing on a missing predecessor.
        issues = job_issues(state, j, id in mismatches) if not integrity else []
        details.append(
            dict(
                job_id=id,
                container_id=j["container_id"],
                status=j["status"],
                source_id=j["source_id"],
                target_id=j["target_id"],
                equipment_id=j["equipment_id"],
                issues=issues,
                requirements=requirements(state, j),
            )
        )
    pending = [d for d in details if d["status"] != "completed"]
    frontier = (
        [
            d
            for d in pending
            if all(
                jobs[p]["status"] == "completed"
                for p in jobs[d["job_id"]]["dependencies"]
            )
        ]
        if not integrity
        else []
    )
    next_work = (
        next((d for d in frontier if d["status"] == "running"), None)
        or next((d for d in frontier if not d["issues"]), None)
        or next(iter(frontier), None)
    )
    co = by_id(state["commitments"], row["commitment_id"])
    final = jobs.get(row["final_ids"][0]) if len(row["final_ids"]) == 1 else None
    if integrity or (
        final and final["status"] == "completed" and final.get("completed_at") is None
    ):
        readiness = "Needs review"
    elif final and final["status"] == "completed":
        readiness = (
            "Delivered on time"
            if final["completed_at"] <= co["cutoff"]
            else "Delivered late"
        )
    elif any(i["requires_review"] for d in pending for i in d["issues"]):
        readiness = "Needs review"
    elif state["minute"] > co["cutoff"]:
        readiness = "Cutoff missed"
    elif not next_work:
        readiness = "Needs review"
    elif next_work["status"] == "running":
        readiness = "Work interrupted" if next_work["issues"] else "Work underway"
    else:
        readiness = "Waiting / blocked" if next_work["issues"] else "Next move ready"
    return dict(
        **row,
        readiness=readiness,
        next_job_id=next_work["job_id"] if next_work else None,
        chain=details,
        integrity=integrity,
        attention=readiness
        in (
            "Needs review",
            "Cutoff missed",
            "Delivered late",
            "Work interrupted",
            "Waiting / blocked",
        ),
        cutoff=co["cutoff"],
    )


def diagnose(store, run, revision=None):
    with store.connect() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        head = c.execute("SELECT revision FROM runs WHERE id=%s", (run,)).fetchone()
        if not head:
            raise RuleError("Run not found")
        rev = head["revision"] if revision is None else revision
        snap = c.execute(
            "SELECT state FROM snapshots WHERE run_id=%s AND revision=%s", (run, rev)
        ).fetchone()
        if not snap:
            raise RuleError("Snapshot not found")
        current = rev == head["revision"]
        state = store.read(run, c) if current else snap["state"]
        params = dict(
            run=run, current=current, state=Jsonb(state), minute=state["minute"]
        )
        scopes = c.execute(DEPENDENCIES, params).fetchall()
        manifest = [describe_visit(state, row) for row in scopes]
        departures = c.execute(
            SUMMARY, dict(state=Jsonb(state), rows=Jsonb(manifest))
        ).fetchall()
        calendar = c.execute(CALENDAR, params).fetchall()
        receipts = c.execute(
            "SELECT id,entity_id,field,status,reason,observed_minute,receive_minute,applied_revision FROM feed_receipts WHERE run_id=%s AND applied_revision<=%s ORDER BY receive_minute,ordinal LIMIT 200",
            (run, rev),
        ).fetchall()
        # One all-departure query also makes resource contention across services visible.
        for lane in calendar:
            equipment_id = lane["equipment_id"]
            lane["commitments"] = sorted(
                {
                    r["commitment_id"]
                    for r in manifest
                    for d in r["chain"]
                    if d["status"] != "completed"
                    and (
                        d["equipment_id"] == equipment_id
                        or equipment_id in jobs_resources(state, d["job_id"])
                    )
                }
            )
        return dict(
            run=run,
            revision=rev,
            minute=state["minute"],
            historical=not current,
            departures=departures,
            manifest=manifest,
            calendar=calendar,
            receipts=receipts,
            dataset=state.get("dataset"),
            limitations=[
                "Readiness describes the next move, not a promise of on-time delivery.",
                "Calendar shows published windows and recorded activity, not future job reservations.",
                "Guidance identifies the next review; it does not approve or rewrite work.",
            ],
        )


def jobs_resources(state, id):
    return by_id(state["jobs"], id).get("resources", [])
