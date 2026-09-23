"""Explicit stage transitions; a reservation never substitutes for actual custody."""

from copy import deepcopy
from .domain import RuleError, by_id, location
from .movement import make_row, calendar_ok, route


def emit(s, events, j, kind, message):
    events.append(
        dict(
            kind=kind,
            entity_id=j["container_id"],
            job_id=j["id"],
            valid_minute=s["minute"],
            message=message,
            custody=deepcopy(by_id(s["containers"], j["container_id"]).get("custody")),
        )
    )


def blocked(s, j):
    reasons = [
        f"{eid} failed; custody retained"
        for eid in j.get("resources", [])
        if by_id(s["equipment"], eid)["status"] != "available"
    ]
    p = j["movement_stages"][j["stage_index"]]
    if p.get("route"):
        closed = {e["id"] for e in s["movement"]["edges"] if e.get("closed")}
        if closed.intersection(p["route"]["edges"]):
            reasons.append("Route closed; movement paused at recorded progress")
    if j.get("waiting_reason"):
        reasons.append(j["waiting_reason"])
    return reasons


def acquire(s, j, p):
    for eid in p["resources"]:
        e = by_id(s["equipment"], eid)
        if e["status"] != "available" or e["job_id"] not in (None, j["id"]):
            return f'{eid} unavailable for {p["name"]}; current custody retained'
    # One loaded tractor at each receiving transfer point. No invisible buffer.
    if p["kind"] == "transfer" and any(
        other["id"] != j["id"]
        and other["status"] == "running"
        and other.get("transfer_claim") == j["target_id"]
        for other in s["jobs"]
    ):
        return "Receiving transfer point occupied; wait at pickup"
    if p["kind"] == "pickup":
        c = by_id(s["containers"], j["container_id"])
        if c["location_id"] != j["source_id"] or any(
            x["location_id"] == c["location_id"] and x["tier"] > c["tier"]
            for x in s["containers"]
            if location(s, j["source_id"])["kind"] == "yard"
        ):
            return "Pickup access changed; cargo remains at source"
    for eid in j.get("resources", []):
        if eid not in p["resources"]:
            by_id(s["equipment"], eid)["job_id"] = None
    for eid in p["resources"]:
        by_id(s["equipment"], eid)["job_id"] = j["id"]
    j["resources"] = list(p["resources"])
    c = by_id(s["containers"], j["container_id"])
    if p["kind"] in ("pickup", "setdown"):
        handler = next(
            e for e in p["resources"] if by_id(s["equipment"], e)["kind"] != "tractor"
        )
        c.update(
            location_id=None,
            job_id=j["id"],
            tier=0,
            custody=dict(kind="equipment", id=handler),
        )
    if p["kind"] == "transfer":
        j["transfer_claim"] = j["target_id"]
    return None


def start(s, j, resources):
    actual = s
    if "_execution_duration_factor" in s:
        actual = dict(s, duration_factor=s["_execution_duration_factor"])
    r = make_row(actual, j, s["minute"], resources)
    if not calendar_ok(s, r):
        raise RuleError("Stage bookings exceed published equipment availability")
    j["movement_stages"] = deepcopy(r["stages"])
    j["assigned_resources"] = list(resources)
    j["resources"] = []
    j["stage_index"] = 0
    reason = acquire(s, j, r["stages"][0])
    if reason:
        raise RuleError(reason)
    j["stage_history"] = [
        dict(
            name=r["stages"][0]["name"],
            start=s["minute"],
            end=None,
            resources=list(j["resources"]),
        )
    ]
    j.update(
        status="running",
        started_at=s["minute"],
        stage_remaining=r["stages"][0]["end"] - r["start"],
        remaining=r["end"] - r["start"],
        waiting_reason=None,
        movement_digest=r["movement_digest"],
    )


def advance(s, j, events):
    # A repaired handover can be retried; recorded wait text is not a permanent guard.
    j["waiting_reason"] = None
    if blocked(s, j):
        return
    p = j["movement_stages"][j["stage_index"]]
    if j["stage_remaining"] > 0:
        j["stage_remaining"] -= 1
        j["remaining"] = max(0, j["remaining"] - 1)
    if p.get("route"):
        from .movement import position

        tractor_id = next(
            e
            for e in j["assigned_resources"]
            if by_id(s["equipment"], e)["kind"] == "tractor"
        )
        by_id(s["equipment"], tractor_id).update(
            position(s, p["route"], 1 - j["stage_remaining"] / (p["end"] - p["start"]))
        )
    if j["stage_remaining"]:
        return
    tractor = next(
        e
        for e in j["assigned_resources"]
        if by_id(s["equipment"], e)["kind"] == "tractor"
    )
    c = by_id(s["containers"], j["container_id"])
    if p["kind"] in ("empty", "transfer"):
        by_id(s["equipment"], tractor)["node_id"] = p["route"]["target"]
    if p["kind"] == "pickup":
        c["custody"] = dict(kind="equipment", id=tractor)
    if j["stage_index"] + 1 < len(j["movement_stages"]):
        nxt = j["movement_stages"][j["stage_index"] + 1]
        reason = acquire(s, j, nxt)
        if reason:
            j["waiting_reason"] = reason
            emit(s, events, j, "move.waiting", reason)
            return
        j["stage_history"][-1]["end"] = s["minute"]
        j["stage_history"].append(
            dict(
                name=nxt["name"],
                start=s["minute"],
                end=None,
                resources=list(j["resources"]),
            )
        )
        j["stage_index"] += 1
        j["stage_remaining"] = nxt["end"] - nxt["start"]
        emit(
            s,
            events,
            j,
            "move.handover",
            f'{j["id"]}: {nxt["name"]}; ownership confirmed',
        )
        return
    j["stage_history"][-1]["end"] = s["minute"]
    # Placement is a real transition, not expiry of a booking.
    c.update(
        location_id=j["target_id"],
        job_id=None,
        tier=max(
            [x["tier"] for x in s["containers"] if x["location_id"] == j["target_id"]],
            default=-1,
        )
        + 1,
        custody=dict(kind="location", id=j["target_id"]),
    )
    for eid in j["resources"]:
        by_id(s["equipment"], eid)["job_id"] = None
    j.update(
        status="completed",
        completed_at=s["minute"],
        remaining=0,
        resources=[],
        transfer_claim=None,
    )
    s.setdefault("position_observed", {})[c["id"]] = s["minute"]
    s.setdefault("input_provenance", {})[f'{c["id"]}/container.position'] = dict(
        source="simulator",
        observed_minute=s["minute"],
        received_minute=s["minute"],
        known_revision=s["revision"] + 1,
        value=dict(location_id=c["location_id"], tier=c["tier"]),
        event_id=f'{j["id"]}/completed',
    )
    emit(s, events, j, "move.completed", f'{j["id"]} placed at {j["target_id"]}')


def validate_custody(s):
    for c in s["containers"]:
        owner = c.get("custody")
        if c["location_id"]:
            # Accepted inventory corrections retain their canonical authority.
            if owner != dict(kind="location", id=c["location_id"]):
                raise RuleError("Location/custody mismatch")
        elif not owner or owner["kind"] != "equipment":
            raise RuleError("In-flight cargo must have an equipment owner")
        else:
            e = by_id(s["equipment"], owner["id"])
            if not e or e["job_id"] != c["job_id"]:
                raise RuleError("Cargo custodian does not own its active work")
