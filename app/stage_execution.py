"""Execute approved stage rows using the same custody transitions as independent replay."""

from .domain import RuleError, by_id, blockers, dispatch
from .movement import make_row
from .schedule_execution import interrupt


def scheduled_dispatch(s, events):
    plan = s["schedule"]
    if plan["status"] not in ("approved", "executing"):
        return
    if any(e["kind"] == "input.applied" for e in events):
        interrupt(s, events, "Accepted input changed the planning basis")
        return
    pending = [
        r
        for r in plan["rows"]
        if by_id(s["jobs"], r["job_id"])["status"] != "completed"
    ]
    for r in pending:
        j = by_id(s["jobs"], r["job_id"])
        if j["status"] == "running" and (blockers(s, j) or s["minute"] >= r["end"]):
            interrupt(
                s, events, f'{j["id"]}: stage blocked/overrun; actual custody retained'
            )
            return
        if any(by_id(s["equipment"], e)["status"] == "failed" for e in r["resources"]):
            interrupt(
                s, events, f'{j["id"]}: assigned equipment failed; inspect custody'
            )
            return
    if not pending:
        plan["status"] = "completed"
        s["running"] = False
        events.append(
            dict(
                kind="schedule.completed",
                entity_id=plan["id"],
                message="All booked stage movements completed; unserved cargo remains visible",
            )
        )
        return
    for r in sorted(pending, key=lambda r: (r["start"], r["job_id"])):
        j = by_id(s["jobs"], r["job_id"])
        if j["status"] != "queued" or r["start"] > s["minute"]:
            continue
        try:
            if r["start"] != s["minute"]:
                raise RuleError("Missed stage start")
            j["equipment_id"] = r["resources"][0]
            if make_row(s, j, s["minute"], r["resources"]) != r:
                raise RuleError("Route, position or stage basis changed")
            dispatch(s, j, r["resources"])
            plan["status"] = "executing"
            events.append(
                dict(
                    kind="move.dispatched",
                    entity_id=j["container_id"],
                    job_id=j["id"],
                    message="Approved stages started; delivery not yet confirmed",
                )
            )
        except RuleError as exc:
            interrupt(s, events, str(exc))
            return
