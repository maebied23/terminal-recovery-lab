"""Bounded relocation decisions. Pure work-instruction changes; no physical movement.

SQL shortlists destinations. Shared scheduling + independent replay validate timing.
Geometry is a distance proxy, never silently converted into calibrated duration.
"""

from copy import deepcopy
from .domain import RuleError, by_id, eligible_equipment, validate, blockers
from .scheduling import greedy, replay, outcomes


def guard(s, job_id):
    j = by_id(s["jobs"], job_id)
    if s.get("data_mode", "synthetic") != "synthetic":
        raise RuleError("Only synthetic instruction writeback is implemented")
    if s["running"] or s.get("schedule"):
        raise RuleError(
            "Pause and return to automatic dispatch before changing destinations"
        )
    if not j or j["kind"] != "rehandle" or j["status"] != "queued":
        raise RuleError("Select a queued relocation")
    if len(s["jobs"]) > 120 or len(s["equipment"]) > 30:
        raise RuleError("Placement limit: 120 jobs and 30 equipment units")
    from .movement import unknown_completion

    if any(
        x["status"] == "running" and (blockers(s, x) or unknown_completion(s, x))
        for x in s["jobs"]
    ):
        raise RuleError(
            "Repair suspended in-progress work before comparing destinations"
        )
    return j


def rewrite(snapshot, job_id, destination):
    s = deepcopy(snapshot)
    j = guard(s, job_id)
    loc = by_id(s["locations"], destination)
    if not loc or loc["kind"] != "yard" or destination == j["source_id"]:
        raise RuleError("Choose a different yard stack")
    old = j["target_id"]
    # Only the immediate same-visit handoff is rewritten. Never guess a later leg.
    following = [
        x
        for x in s["jobs"]
        if x["container_id"] == j["container_id"]
        and j["id"] in x["dependencies"]
        and x["source_id"] == old
    ]
    unfinished = [
        x
        for x in s["jobs"]
        if x["container_id"] == j["container_id"]
        and x["id"] != j["id"]
        and x["status"] != "completed"
    ]
    if len(following) > 1 or (unfinished and len(following) != 1):
        raise RuleError("Ambiguous downstream pickup; review the work instructions")
    if any(x["status"] != "queued" for x in following):
        raise RuleError("A downstream pickup has already started")
    changes = [dict(job_id=j["id"], field="target_id", before=old, after=destination)]
    j["target_id"] = destination
    for x in following:
        changes.append(
            dict(job_id=x["id"], field="source_id", before=old, after=destination)
        )
        x["source_id"] = destination
    for x in [j, *following]:
        eligible = eligible_equipment(s, x)
        if not eligible:
            raise RuleError("No compatible primary equipment for the revised route")
        if x["equipment_id"] not in {e["id"] for e in eligible}:
            new = sorted(eligible, key=lambda e: e["id"])[0]["id"]
            changes.append(
                dict(
                    job_id=x["id"],
                    field="equipment_id",
                    before=x["equipment_id"],
                    after=new,
                )
            )
            x["equipment_id"] = new
    validate(s)
    return s, changes


def compare(snapshot, job_id, facts):
    j = guard(snapshot, job_id)
    if snapshot.get("movement"):
        from .movement import route

        facts = deepcopy(facts)
        cargo = by_id(snapshot["containers"], j["container_id"])
        co = by_id(snapshot["commitments"], cargo["commitment_id"])
        for f in facts:
            f["static_screen"] = f["excluded_reason"]
            try:
                f["immediate_distance"] = route(
                    snapshot, j["source_id"], f["destination"]
                )["metres"]
                f["onward_distance"] = (
                    route(snapshot, f["destination"], co["location_id"])["metres"]
                    if co
                    else 0
                )
                f["excluded_reason"] = None
            except RuleError as exc:
                f["excluded_reason"] = str(exc)
        # Include differing capacity conditions, not just four nearest stacks.
        feasible = sorted(
            (f for f in facts if not f["prescribed"]),
            key=lambda f: (
                bool(f["excluded_reason"]),
                f["immediate_distance"] + f["onward_distance"],
                f["destination"],
            ),
        )
        diverse = sorted(
            feasible, key=lambda f: (-f["free_slots"], f["committed"], f["destination"])
        )
        shortlist = feasible[:2] + [f for f in diverse if f not in feasible[:2]][:2]
        facts = (
            [f for f in facts if f["prescribed"]]
            + shortlist
            + [f for f in feasible if f not in shortlist]
        )
    chosen = [x for x in facts if x["prescribed"]]
    chosen += [x for x in facts if not x["excluded_reason"] and not x["prescribed"]][:4]
    candidates = []
    end = snapshot["minute"] + 180
    for fact in chosen:
        candidate = dict(**fact, validation="rejected")
        candidates.append(candidate)
        if fact["excluded_reason"]:
            candidate["error"] = fact["excluded_reason"]
            continue
        try:
            proposed, changes = rewrite(snapshot, job_id, fact["destination"])
            rows = greedy(proposed, end)
            replay(proposed, rows, end)
            if job_id not in {r["job_id"] for r in rows}:
                raise RuleError("Relocation cannot be scheduled within this horizon")
            candidate.update(
                validation="passed",
                changes=changes,
                rows=rows,
                **outcomes(proposed, rows, end)
            )
            if snapshot.get("movement"):
                selected_row = next(r for r in rows if r["job_id"] == job_id)
                candidate["movement"] = dict(
                    start=selected_row["start"],
                    end=selected_row["end"],
                    stages=selected_row["stages"],
                    units="metres",
                    conditional_capacity=True,
                )
        except RuleError as exc:
            candidate["error"] = str(exc)
    valid = [c for c in candidates if c["validation"] == "passed"]

    def rank(c):
        m = c["metrics"]
        return (
            m["missed"],
            m["lateness"],
            m["rehandles"],
            c["immediate_distance"] + c["onward_distance"],
            not c["prescribed"],
            c["destination"],
        )

    best = min(valid, key=rank) if valid else None
    baseline = next((c for c in valid if c["prescribed"]), None)
    for c in valid:
        c["impact"] = [
            dict(
                id=co["id"],
                on_time=co["on_time"],
                total=co["total"],
                delta=(
                    co["on_time"]
                    - next(
                        b["on_time"]
                        for b in baseline["services"]
                        if b["id"] == co["id"]
                    )
                    if baseline
                    else None
                ),
            )
            for co in c["services"]
        ]
    return dict(
        job_id=job_id,
        container_id=j["container_id"],
        base_revision=snapshot["revision"],
        prescribed=j["target_id"],
        end_minute=end,
        facts=facts,
        candidates=candidates,
        recommended=best["destination"] if best else None,
        method=(
            "placement-v2: metric routes + temporal replay + SQL occupancy"
            if snapshot.get("movement")
            else "placement-v1: SQL shortlist + deadline scheduling + physical replay"
        ),
        assumptions=(
            [
                "Authored synthetic metres and travel rates, not calibrated terminal measurements.",
                "Capacity becomes available only after actual pickup; profiles show conditional planned vacancy.",
                "Empty tractor travel and independently released handling stages included.",
                "Prescribed destination plus four bounded alternatives; no claim of global yard optimum.",
                "All terminal work competes; no automatic booking or authority release.",
            ]
            if snapshot.get("movement")
            else [
                "At most four alternative stacks plus the prescribed destination.",
                "Whole-move equipment reservations; all terminal work competes.",
                "Distance uses schematic coordinates, not metres or calibrated travel time.",
                "Existing handling/transfer durations are unchanged for every alternative.",
                "Reject stacks covering committed cargo; count queued and in-flight arrivals conservatively.",
                "No new hold release, future input knowledge, or autonomous booking.",
            ]
        ),
    )


def apply(s, proposal, destination, events):
    if proposal["base_revision"] != s["revision"]:
        raise RuleError("Placement is stale; compare again")
    c = next(
        (x for x in proposal["candidates"] if x["destination"] == destination), None
    )
    if not c or c["validation"] != "passed" or c["excluded_reason"]:
        raise RuleError("Destination did not pass placement validation")
    if destination == proposal["prescribed"]:
        raise RuleError("The prescribed destination already applies")
    proposed, changes = rewrite(s, proposal["job_id"], destination)
    if changes != c["changes"]:
        raise RuleError("Work instructions changed; compare again")
    replay(proposed, c["rows"], proposal["end_minute"])
    s["jobs"] = proposed["jobs"]
    for change in changes:
        job = by_id(s["jobs"], change["job_id"])
        job["placement_basis"] = dict(
            proposal_id=proposal["id"],
            revision=proposal["base_revision"],
            destination=destination,
            method=proposal["method"],
        )
    events.append(
        dict(
            kind="placement.approved",
            entity_id=proposal["job_id"],
            job_ids=[x["job_id"] for x in changes],
            changes=changes,
            proposal_id=proposal["id"],
            destination=destination,
            message="Destination and downstream pickup updated; positions unchanged. Build new equipment bookings.",
        )
    )
