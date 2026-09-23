"""Simulator adapter: approval and physical completion are different events."""

from copy import deepcopy
from .domain import RuleError, by_id, blockers, dispatch
from .scheduling import replay, bundles, windows


def activate(s, plan, events):
    if s["running"] or plan["base_revision"] != s["revision"]:
        raise RuleError("Pause and compare again: this schedule is stale")
    if s.get("data_mode", "synthetic") != "synthetic":
        raise RuleError("A real terminal writeback adapter is not implemented")
    replay(s, plan["rows"], plan["end_minute"])
    s["schedule"] = deepcopy(plan)
    s["schedule"].update(status="approved", approved_minute=s["minute"], reason=None)
    events.append(
        dict(
            kind="schedule.approved",
            entity_id=plan["id"],
            message="Future resource bookings accepted by simulator; no cargo moved",
            plan_id=plan["id"],
            base_revision=plan["base_revision"],
        )
    )


def interrupt(s, events, reason):
    plan = s["schedule"]
    if plan["status"] in ("interrupted", "withdrawn", "completed"):
        return
    plan.update(status="interrupted", reason=reason, interrupted_minute=s["minute"])
    s["running"] = False
    events.append(
        dict(
            kind="schedule.interrupted",
            entity_id=plan["id"],
            plan_id=plan["id"],
            message=reason + "; future bookings released. Inspect and compare again.",
        )
    )


def scheduled_dispatch(s, events):
    if s.get("movement"):
        from .stage_execution import scheduled_dispatch as staged

        return staged(s, events)
    plan = s["schedule"]
    if plan["status"] not in ("approved", "executing"):
        return
    if any(e.get("kind") == "input.applied" for e in events):
        interrupt(
            s, events, "New accepted input requires review of the remaining schedule"
        )
        return
    pending = [
        r
        for r in plan["rows"]
        if by_id(s["jobs"], r["job_id"])["status"] != "completed"
    ]
    for r in pending:
        j = by_id(s["jobs"], r["job_id"])
        if j["status"] == "running":
            if blockers(s, j) or s["minute"] >= r["end"]:
                interrupt(s, events, f"{j['id']} could not finish inside its booking")
                return
        elif any(
            by_id(s["equipment"], eid)["status"] != "available"
            for eid in r["resources"]
        ):
            interrupt(s, events, f"A booked resource for {j['id']} is unavailable")
            return
    if not pending:
        plan["status"] = "completed"
        s["running"] = False
        events.append(
            dict(
                kind="schedule.completed",
                entity_id=plan["id"],
                plan_id=plan["id"],
                message="All booked moves completed in simulation; unscheduled obligations remain visible",
            )
        )
        return
    for r in sorted(pending, key=lambda r: (r["start"], r["job_id"])):
        j = by_id(s["jobs"], r["job_id"])
        if j["status"] != "queued" or r["start"] > s["minute"]:
            continue
        if r["start"] != s["minute"]:
            interrupt(s, events, f"Missed dispatch window for {j['id']}")
            return
        original = j["equipment_id"]
        j["equipment_id"] = r["resources"][0]
        try:
            if r["resources"] not in bundles(s, j) or not windows(
                s, r["resources"], r["start"], r["start"], r["end"] - r["start"]
            ):
                raise RuleError(
                    "Booked resources no longer satisfy the calendar / capabilities"
                )
            dispatch(s, j, r["resources"])
        except RuleError as exc:
            j["equipment_id"] = original
            interrupt(s, events, f"{j['id']}: {exc}")
            return
        plan["status"] = "executing"
        events.append(
            dict(
                kind="move.dispatched",
                entity_id=j["container_id"],
                job_id=j["id"],
                plan_id=plan["id"],
                scheduled_start=r["start"],
                scheduled_end=r["end"],
                resources=r["resources"],
                message=f"{j['id']} acknowledged by simulator against approved booking",
            )
        )
