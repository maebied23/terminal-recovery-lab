"""Pure operational rules. No persistence, network, wall clock or global random state."""

from copy import deepcopy
from hashlib import sha256
import math


class RuleError(ValueError):
    pass


def by_id(rows, key):
    return next((x for x in rows if x["id"] == key), None)


def duration(seed, job, factor=1.0):
    # A separate deterministic stream per job; scheduling order cannot consume its noise.
    u = int(sha256(f'{seed}:{job["id"]}'.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return max(1, round(job["duration"] * (0.8 + 0.4 * u) * factor))


def seed_state(profile="standard", seed=42):
    s = dict(
        revision=0,
        minute=0,
        seed=seed,
        policy="fifo",
        running=False,
        speed=1,
        profile=profile,
        locations=[],
        equipment=[],
        containers=[],
        jobs=[],
        commitments=[],
        observations=[],
        plan_id=None,
        duration_factor=1.0,
    )
    for i in range(6):
        block = f"{chr(65+i)}"
        for bay in range(1, 5):
            s["locations"].append(
                dict(
                    id=f"{block}{bay}",
                    kind="yard",
                    zone="west" if i < 3 else "east",
                    capacity=8,
                    block=block,
                    x=160 + (i % 3) * 225 + (bay - 1) * 40,
                    y=265 + (i // 3) * 170,
                    label=f"Block {block} · bay {bay}",
                )
            )
    for id, kind, x, y, cap in [
        ("VESSEL-1", "vessel", 220, 95, 80),
        ("VESSEL-2", "vessel", 740, 95, 80),
        ("GATE-IN", "gate", 100, 590, 40),
        ("TRUCK-OUT", "truck", 350, 590, 40),
        ("RAIL-1", "rail", 780, 565, 12),
        ("RAIL-2", "rail", 780, 625, 12),
    ]:
        s["locations"].append(
            dict(
                id=id, kind=kind, zone="all", capacity=cap, block=id, x=x, y=y, label=id
            )
        )
    for id, kind, zone, x, y in [
        ("YC-1", "yard", "west", 250, 345),
        ("YC-2", "yard", "east", 700, 510),
        ("YC-3", "yard", "all", 500, 345),
        ("QC-1", "quay", "west", 280, 175),
        ("QC-2", "quay", "east", 780, 175),
        ("TT-1", "tractor", "all", 160, 200),
        ("TT-2", "tractor", "all", 440, 200),
        ("TT-3", "tractor", "all", 700, 200),
        ("GATE-1", "gate", "all", 100, 555),
    ]:
        s["equipment"].append(
            dict(id=id, kind=kind, zone=zone, status="available", job_id=None, x=x, y=y)
        )
    for id, kind, loc, cutoff, cap, arrival in [
        ("NORTH-RAIL", "rail", "RAIL-1", 42, 12, 0),
        ("EAST-RAIL", "rail", "RAIL-2", 92, 12, 12),
        ("ROAD-AM", "truck", "TRUCK-OUT", 75, 40, 8),
        ("AURORA", "vessel", "VESSEL-1", 120, 80, 0),
        ("MERIDIAN", "vessel", "VESSEL-2", 155, 80, 15),
    ]:
        s["commitments"].append(
            dict(
                id=id,
                kind=kind,
                location_id=loc,
                cutoff=cutoff,
                capacity=cap,
                arrival=arrival,
                status="scheduled",
            )
        )
    count = 24 if profile == "small" else 144
    for i in range(count):
        loc = s["locations"][i % 24]["id"]
        s["containers"].append(
            dict(
                id=f"CT-{i+1:04}",
                visit_id=f"VIS-{i+1:04}",
                location_id=loc,
                tier=i // 24,
                flow="storage",
                commitment_id=None,
                released=True,
                hold_reason=None,
                weight_t=22 + i % 9,
                job_id=None,
            )
        )

    def addjob(c, source, target, kind, eq, due, deps=None):
        id = f'MV-{len(s["jobs"])+1:03}'
        s["jobs"].append(
            dict(
                id=id,
                container_id=c["id"],
                source_id=source,
                target_id=target,
                kind=kind,
                equipment_id=eq,
                status="queued",
                duration={
                    "discharge": 6,
                    "load": 7,
                    "receive": 4,
                    "retrieve": 5,
                    "rehandle": 3,
                }[kind],
                remaining=0,
                deadline=due,
                dependencies=deps or [],
                started_at=None,
                completed_at=None,
                resources=[],
                release_required=kind in ("retrieve", "load"),
                created_order=len(s["jobs"]),
                travel_minutes=1,
            )
        )
        return id

    # Active cargo sits on top of otherwise inert inventory; IDs/positions still share the same model.
    tops = [
        max(
            [c for c in s["containers"] if c["location_id"] == loc["id"]],
            key=lambda c: c["tier"],
        )
        for loc in s["locations"][:24]
    ]
    for i, c in enumerate(tops[:12]):
        dest = "NORTH-RAIL" if i < 6 else ("EAST-RAIL" if i < 9 else "ROAD-AM")
        co = by_id(s["commitments"], dest)
        c.update(flow="export-rail" if i < 9 else "import-road", commitment_id=dest)
        addjob(
            c,
            c["location_id"],
            co["location_id"],
            "retrieve",
            "YC-1" if i < 12 else "YC-2",
            co["cutoff"],
        )
    # An explicit blocked retrieval: rehandle its cover before the rail job.
    cover = tops[1]
    covered = tops[0]
    cover["location_id"] = covered["location_id"]
    cover["tier"] = covered["tier"] + 1
    first = by_id(s["jobs"], "MV-001")
    second = by_id(s["jobs"], "MV-002")
    rehandle = addjob(
        cover, cover["location_id"], "D4", "rehandle", "YC-1", first["deadline"]
    )
    first["dependencies"] = [rehandle]
    second["dependencies"] = [rehandle]
    second["source_id"] = "D4"
    second["equipment_id"] = "YC-2"
    tops[4].update(released=False, hold_reason="Synthetic authority hold")
    # Six imports: vessel → yard → road/rail, and six exports: gate → yard → vessel.
    for i in range(12):
        c = tops[12 + i]
        loc = c["location_id"]
        inbound = i < 6
        start = "VESSEL-1" if inbound else "GATE-IN"
        end = "ROAD-AM" if inbound else ("AURORA" if i < 9 else "MERIDIAN")
        c.update(
            location_id=start,
            tier=i,
            flow="import" if inbound else "export-vessel",
            commitment_id=end,
        )
        a = addjob(
            c,
            start,
            loc,
            "discharge" if inbound else "receive",
            "QC-1" if inbound else "GATE-1",
            75 if inbound else 120,
        )
        co = by_id(s["commitments"], end)
        addjob(
            c,
            loc,
            co["location_id"],
            "retrieve" if inbound else "load",
            "YC-2" if inbound else ("QC-1" if i < 9 else "QC-2"),
            co["cutoff"],
            [a],
        )
    from .relationships import dependency_detail

    for job in s["jobs"]:
        job["dependency_details"] = {
            d: dict(
                dependency_detail(s, job, by_id(s["jobs"], d)), origin="seeded scenario"
            )
            for d in job["dependencies"]
        }
    s["data_mode"] = "synthetic"
    s["resource_model"] = "coordinated-v2"
    validate(s)
    return s


def location(s, id):
    return by_id(s["locations"], id)


def occupant_count(s, loc):
    return sum(c["location_id"] == loc for c in s["containers"])


def eligible_equipment(s, j):
    kind = (
        "quay"
        if j["kind"] in ("load", "discharge")
        else "gate" if j["kind"] == "receive" else "yard"
    )
    zone = location(s, j["source_id"])["zone"]
    if zone == "all":
        zone = location(s, j["target_id"])["zone"]
    if kind == "quay":
        zone = "west" if "VESSEL-1" in (j["source_id"], j["target_id"]) else "east"
    return [
        e
        for e in s["equipment"]
        if e["kind"] == kind
        and (e["zone"] == "all" or zone == "all" or e["zone"] == zone)
    ]


def requirements(s, j):
    """Capabilities, assignments and reservations are distinct. Synthetic limits."""
    primary = by_id(s["equipment"], j["equipment_id"])
    reqs = [
        dict(
            role="Primary handling",
            capability=primary["kind"],
            assigned=primary["id"],
            eligible=[e["id"] for e in eligible_equipment(s, j)],
        )
    ]
    if s.get("resource_model") == "coordinated-v2":
        yard = next(
            (
                location(s, l)
                for l in (j["source_id"], j["target_id"])
                if location(s, l)["kind"] == "yard"
                and (
                    primary["kind"] != "yard"
                    or primary["zone"] not in ("all", location(s, l)["zone"])
                )
            ),
            None,
        )
        if yard:
            reqs.append(
                dict(
                    role="Yard pickup / placement",
                    capability="yard",
                    assigned=None,
                    eligible=[
                        e["id"]
                        for e in s["equipment"]
                        if e["kind"] == "yard" and e["zone"] in ("all", yard["zone"])
                    ],
                )
            )
    if j["source_id"] != j["target_id"]:
        reqs.append(
            dict(
                role="Internal transport",
                capability="tractor",
                assigned=None,
                eligible=[e["id"] for e in s["equipment"] if e["kind"] == "tractor"],
            )
        )
    for r in reqs:
        r["reserved"] = (
            [eid for eid in j.get("resources", []) if eid in r["eligible"]]
            if j["status"] == "running"
            else []
        )
        r["available"] = [
            eid
            for eid in r["eligible"]
            if by_id(s["equipment"], eid)["status"] == "available"
            and not by_id(s["equipment"], eid)["job_id"]
            and within_shift(s, eid)
        ]
    return reqs


def within_shift(s, equipment_id):
    """Published availability permits dispatch; existing lifts are not abandoned at shift end."""
    if "availability" not in s:
        return True
    return any(
        w["equipment_id"] == equipment_id
        and w["start_minute"] <= s["minute"] < w["end_minute"]
        for w in s["availability"]
    )


def allocate(s, j, ignore_busy=False):
    resources = []
    cargo = by_id(s["containers"], j["container_id"])
    for r in requirements(s, j):
        choices = [
            by_id(s["equipment"], eid)
            for eid in ([r["assigned"]] if r["assigned"] else r["eligible"])
        ]
        choices = [
            e
            for e in choices
            if e["id"] in r["eligible"]
            and e["status"] == "available"
            and within_shift(s, e["id"])
            and (ignore_busy or not e["job_id"])
            and (
                e["kind"] not in ("yard", "quay")
                or cargo["weight_t"] <= e.get("lifting_capacity_t", 50)
            )
            and e["id"] not in resources
        ]
        if not choices:
            return None
        resources.append(min(choices, key=lambda e: e["id"])["id"])
    return resources


def blockers(s, j, ignore_busy=False):
    if j["status"] == "completed":
        return []
    if j["status"] == "running":
        if s.get("movement"):
            from .move_execution import blocked

            return blocked(s, j)
        return [
            f"{r} failed; move paused"
            for r in j["resources"]
            if by_id(s["equipment"], r)["status"] == "failed"
        ]
    c = by_id(s["containers"], j["container_id"])
    reasons = []
    if s.get("movement"):
        from .movement import route

        try:
            route(s, j["source_id"], j["target_id"])
        except RuleError as exc:
            reasons.append(str(exc))
        if any(
            x["status"] == "running" and x["container_id"] == c["id"] for x in s["jobs"]
        ):
            reasons.append("Cargo already has active work")
    if any(by_id(s["jobs"], d)["status"] != "completed" for d in j["dependencies"]):
        reasons.append("Predecessor move incomplete")
    if c["location_id"] != j["source_id"]:
        reasons.append("Cargo not at planned pickup")
    if j["release_required"] and not c["released"]:
        reasons.append("Outbound authority hold")
    if (
        c["location_id"] == j["source_id"]
        and location(s, j["source_id"])["kind"] == "yard"
        and any(
            x["location_id"] == c["location_id"] and x["tier"] > c["tier"]
            for x in s["containers"]
        )
    ):
        reasons.append("Another container is stacked above")
    co = by_id(s["commitments"], c["commitment_id"])
    if co and j["kind"] in ("retrieve", "load"):
        if s["minute"] < co["arrival"]:
            reasons.append("Outbound service not open")
        if s["minute"] > co["cutoff"] or co["status"] == "departed":
            reasons.append("Outbound service closed")
    # Discharge is possible only while the named vessel remains alongside.
    sourceco = next(
        (x for x in s["commitments"] if x["location_id"] == j["source_id"]), None
    )
    if (
        j["kind"] == "discharge"
        and sourceco
        and not (sourceco["arrival"] <= s["minute"] <= sourceco["cutoff"])
    ):
        reasons.append("Vessel not alongside")
    reserved = sum(
        x["status"] == "running" and x["target_id"] == j["target_id"] for x in s["jobs"]
    )
    if (
        occupant_count(s, j["target_id"]) + reserved
        >= location(s, j["target_id"])["capacity"]
    ):
        reasons.append("Destination capacity reserved/full")
    if s.get("movement") and location(s, j["target_id"])["kind"] == "yard":
        own = by_id(s["commitments"], c["commitment_id"])
        for resident in s["containers"]:
            obligation = by_id(s["commitments"], resident["commitment_id"])
            if (
                resident["location_id"] == j["target_id"]
                and obligation
                and (not own or obligation["cutoff"] < own["cutoff"])
            ):
                reasons.append(
                    f"Placement would cover {resident['id']} with an earlier/known retrieval obligation"
                )
    eq = by_id(s["equipment"], j["equipment_id"])
    if eq not in eligible_equipment(s, j):
        reasons.append("Equipment outside operating envelope")
    if eq["status"] == "failed":
        reasons.append(f'{eq["id"]} unavailable')
    elif not within_shift(s, eq["id"]):
        reasons.append(f'{eq["id"]} outside published availability')
    elif eq["job_id"] and not ignore_busy:
        reasons.append(f'{eq["id"]} busy')
    if not ignore_busy and not any(
        e["kind"] == "tractor" and e["status"] == "available" and not e["job_id"]
        for e in s["equipment"]
    ):
        reasons.append("No free internal tractor")
    if allocate(s, j, ignore_busy) is None and not any(
        "busy" in r or "unavailable" in r or "tractor" in r or "envelope" in r
        for r in reasons
    ):
        reasons.append(
            "Required handling resources unavailable or lifting limit exceeded"
        )
    return reasons


def ordered_jobs(s):
    def order(j):
        co = by_id(
            s["commitments"], by_id(s["containers"], j["container_id"])["commitment_id"]
        )
        if s["policy"] == "rail-first":
            return (
                0 if (co and co["kind"] == "rail") or j["kind"] == "rehandle" else 1,
                j["deadline"],
                j["created_order"],
            )
        if s["policy"] == "deadline":
            return (j["deadline"], j["created_order"])
        if s["policy"] == "vessel-first":
            return (
                0 if j["kind"] in ("load", "discharge", "receive") else 1,
                j["deadline"],
                j["created_order"],
            )
        return (j["created_order"],)

    return sorted([j for j in s["jobs"] if j["status"] == "queued"], key=order)


def dispatch(s, j, resources=None):
    reasons = blockers(s, j)
    if reasons:
        raise RuleError("; ".join(reasons))
    c = by_id(s["containers"], j["container_id"])
    if resources is None:
        resources = allocate(s, j)
    else:
        reqs = requirements(s, j)
        if len(resources) != len(reqs) or len(set(resources)) != len(resources):
            raise RuleError("Invalid synchronized resource bundle")
        cargo = by_id(s["containers"], j["container_id"])
        for eid, req in zip(resources, reqs):
            eq = by_id(s["equipment"], eid)
            if (
                eid not in req["eligible"]
                or (req["assigned"] and eid != req["assigned"])
                or not eq
                or eq["status"] != "available"
                or eq["job_id"]
                or not within_shift(s, eid)
                or eq["kind"] in ("yard", "quay")
                and cargo["weight_t"] > eq.get("lifting_capacity_t", 50)
            ):
                raise RuleError("Booked resource is no longer available or compatible")
    if s.get("movement"):
        from .move_execution import start

        start(s, j, resources)
        return
    j.update(
        status="running",
        remaining=duration(s["seed"], j, s["duration_factor"]) + j["travel_minutes"],
        started_at=s["minute"],
        resources=resources,
    )
    for r in j["resources"]:
        by_id(s["equipment"], r)["job_id"] = j["id"]
    c.update(location_id=None, job_id=j["id"], tier=0)


def tick(s, before_tick=None, dispatch_hook=None):
    """One simulated minute; completions then departures then eligible dispatch."""
    s = deepcopy(s)
    events = []
    s["minute"] += 1
    if before_tick:
        events.extend(before_tick(s))
    for j in s["jobs"]:
        if s.get("movement") and j["status"] == "running":
            from .move_execution import advance

            advance(s, j, events)
            continue
        if j["status"] != "running" or blockers(s, j):
            continue
        j["remaining"] -= 1
        if j["remaining"] <= 0:
            c = by_id(s["containers"], j["container_id"])
            c.update(
                location_id=j["target_id"],
                tier=max(
                    [
                        x["tier"]
                        for x in s["containers"]
                        if x["location_id"] == j["target_id"]
                    ],
                    default=-1,
                )
                + 1,
                job_id=None,
            )
            j.update(status="completed", completed_at=s["minute"])
            if "dataset" in s:
                s.setdefault("position_observed", {})[c["id"]] = s["minute"]
                s.setdefault("input_provenance", {})[
                    f'{c["id"]}/container.position'
                ] = dict(
                    source="simulator",
                    observed_minute=s["minute"],
                    received_minute=s["minute"],
                    known_revision=s["revision"] + 1,
                    value=dict(location_id=c["location_id"], tier=c["tier"]),
                    sequence=-1,
                    event_id=f'{j["id"]}/completed',
                )
            for r in j["resources"]:
                by_id(s["equipment"], r)["job_id"] = None
            events.append(
                dict(
                    kind="move.completed",
                    entity_id=j["container_id"],
                    job_id=j["id"],
                    message=f'{j["id"]} completed at {j["target_id"]}',
                )
            )
    if s.get("movement"):
        # Complete all releases before retrying zero-time handovers at this boundary.
        from .move_execution import advance

        for j in s["jobs"]:
            if j["status"] == "running" and j.get("stage_remaining") == 0:
                advance(s, j, events)
    for co in s["commitments"]:
        if co["status"] == "scheduled" and s["minute"] >= co["arrival"]:
            co["status"] = "open"
        if co["status"] in ("open", "closing") and s["minute"] > co["cutoff"]:
            # Close admission at cutoff, but do not depart with an in-flight lift.
            working = any(
                j["status"] == "running"
                and co["location_id"] in (j["source_id"], j["target_id"])
                for j in s["jobs"]
            )
            co["status"] = "closing" if working else "departed"
            if not working:
                events.append(
                    dict(
                        kind="service.departed",
                        entity_id=co["id"],
                        message=f'{co["id"]} departed after closing admission',
                    )
                )
    if dispatch_hook:
        dispatch_hook(s, events)
    elif s.get("schedule"):
        from .schedule_execution import scheduled_dispatch

        scheduled_dispatch(s, events)
    else:
        for j in ordered_jobs(s):
            if not blockers(s, j):
                dispatch(s, j)
                events.append(
                    dict(
                        kind="move.dispatched",
                        entity_id=j["container_id"],
                        job_id=j["id"],
                        message=f'{j["id"]} acknowledged by simulator',
                    )
                )
    for event in events:
        event["valid_minute"] = s["minute"]
    validate(s)
    return s, events


def validate(s):
    if s.get("movement"):
        from .move_execution import validate_custody

        validate_custody(s)
    collections = {
        k: {x["id"] for x in s[k]}
        for k in ("jobs", "containers", "locations", "equipment", "commitments")
    }
    for k, ids_ in collections.items():
        if len(ids_) != len(s[k]):
            raise RuleError(f"Duplicate {k} identity")
    jobs = {j["id"]: j for j in s["jobs"]}
    visiting, visited = set(), set()

    def visit(jid):
        if jid in visiting:
            raise RuleError("Circular job dependency")
        if jid in visited:
            return
        visiting.add(jid)
        for dep in jobs[jid]["dependencies"]:
            if dep not in jobs:
                raise RuleError("Unknown predecessor")
            visit(dep)
        visiting.remove(jid)
        visited.add(jid)

    for j in s["jobs"]:
        for field, collection in (
            ("container_id", "containers"),
            ("source_id", "locations"),
            ("target_id", "locations"),
            ("equipment_id", "equipment"),
        ):
            if j[field] not in collections[collection]:
                raise RuleError(f"Unknown job {field}")
        if len(j["dependencies"]) != len(set(j["dependencies"])):
            raise RuleError("Duplicate predecessor")
        visit(j["id"])
    for c in s["containers"]:
        if c["location_id"] and c["location_id"] not in collections["locations"]:
            raise RuleError("Unknown cargo location")
        if c["commitment_id"] and c["commitment_id"] not in collections["commitments"]:
            raise RuleError("Unknown commitment")

    ids = [c["id"] for c in s["containers"]]
    if len(ids) != len(set(ids)):
        raise RuleError("Duplicate container identity")
    for c in s["containers"]:
        if (c["location_id"] is None) == (c["job_id"] is None):
            raise RuleError("Cargo must be at one location or on one move")
        if c["job_id"]:
            j = by_id(s["jobs"], c["job_id"])
            if not j or j["status"] != "running" or j["container_id"] != c["id"]:
                raise RuleError("Orphaned in-transit cargo")
    for loc in s["locations"]:
        occupied = [c for c in s["containers"] if c["location_id"] == loc["id"]]
        reserved = sum(
            j["status"] == "running" and j["target_id"] == loc["id"] for j in s["jobs"]
        )
        if len(occupied) + reserved > loc["capacity"]:
            raise RuleError("Location capacity violated")
        if loc["kind"] == "yard" and len({c["tier"] for c in occupied}) != len(
            occupied
        ):
            raise RuleError("Two containers occupy one stack tier")
    busy = []
    for j in s["jobs"]:
        if j["status"] == "running":
            if any(
                by_id(s["jobs"], d)["status"] != "completed" for d in j["dependencies"]
            ):
                raise RuleError("Precedence violation")
            busy.extend(j["resources"])
            if any(
                by_id(s["equipment"], r)["job_id"] != j["id"] for r in j["resources"]
            ):
                raise RuleError("Resource reservation inconsistent")
    if len(busy) != len(set(busy)):
        raise RuleError("Resource double assignment")


def apply_policy(s, policy):
    if policy not in ("fifo", "rail-first", "deadline", "vessel-first"):
        raise RuleError("Unknown policy")
    s["policy"] = policy
    # Balance reachable queued work. Never move a failed crane's in-flight load to another crane.
    if policy != "fifo":
        loads = {e["id"]: 0 for e in s["equipment"]}
        for j in ordered_jobs(s):
            choices = [
                e for e in eligible_equipment(s, j) if e["status"] == "available"
            ]
            if choices:
                eq = min(
                    choices,
                    key=lambda e: (loads[e["id"]] + (6 if e["job_id"] else 0), e["id"]),
                )
                j["equipment_id"] = eq["id"]
                loads[eq["id"]] += j["duration"]


def transition(s, command, before_tick=None):
    s = deepcopy(s)
    action = command["action"]
    events = []
    if s.get("data_mode", "synthetic") != "synthetic" and action in (
        "advance",
        "clock",
        "dispatch",
        "approve_plan",
        "approve_access",
        "approve_schedule",
    ):
        raise RuleError("Simulation actions cannot mutate observed external state")
    if s.get("schedule") and action in ("dispatch", "approve_plan", "approve_access"):
        raise RuleError(
            "An approved schedule controls dispatch. Withdraw it before changing work instructions."
        )
    if action == "approve_placement":
        from .placement import apply as apply_placement

        apply_placement(s, command["placement"], command["destination_id"], events)
    elif action == "approve_schedule":
        from .schedule_execution import activate

        activate(s, command["schedule_plan"], events)
    elif action == "withdraw_schedule":
        from .schedule_execution import interrupt

        if not s.get("schedule"):
            raise RuleError("No approved schedule to withdraw")
        interrupt(
            s,
            events,
            "Planner withdrew future bookings; in-progress work remains frozen",
        )
        s["schedule"]["status"] = "withdrawn"
    elif action == "resume_dispatch":
        if s.get("schedule", {}).get("status") not in (
            "withdrawn",
            "completed",
            "interrupted",
        ):
            raise RuleError(
                "Withdraw the schedule before returning to automatic dispatch"
            )
        s.pop("schedule", None)
    elif action == "approve_access":
        from .rehandles import apply

        proposal, added = apply(s, command["entity_id"], command["proposal_token"])
        events.append(
            dict(
                kind="plan.access_approved",
                entity_id=command["entity_id"],
                job_ids=added,
                proposal=proposal,
                message=f"Access work created: {', '.join(added)}; cargo positions unchanged",
            )
        )
    elif action == "advance":
        for _ in range(command.get("minutes", 1)):
            s, ev = tick(s, before_tick)
            events.extend(ev)
            if any(
                e["kind"] in ("schedule.interrupted", "schedule.completed") for e in ev
            ):
                break
    elif action == "pause":
        s["running"] = False
    elif action == "clock":
        s["running"] = command["running"]
        s["speed"] = command.get("speed", s["speed"])
    elif action == "obstruct":
        cargo = by_id(s["containers"], command["entity_id"])
        if (
            not cargo
            or not cargo["location_id"]
            or location(s, cargo["location_id"])["kind"] != "yard"
        ):
            raise RuleError("Choose cargo currently in a yard stack")
        loc = location(s, cargo["location_id"])
        if (
            occupant_count(s, loc["id"])
            + sum(
                j["status"] == "running" and j["target_id"] == loc["id"]
                for j in s["jobs"]
            )
            >= loc["capacity"]
        ):
            raise RuleError("No capacity for a synthetic cover")
        if any(
            j["status"] == "running" and loc["id"] in (j["source_id"], j["target_id"])
            for j in s["jobs"]
        ):
            raise RuleError(
                "Pause handling at the target stack before injecting a cover"
            )
        covers = [
            c
            for c in s["containers"]
            if not c["commitment_id"]
            and c["location_id"]
            and c["location_id"] != loc["id"]
            and location(s, c["location_id"])["kind"] == "yard"
            and location(s, c["location_id"])["zone"] == loc["zone"]
            and not any(
                x["location_id"] == c["location_id"] and x["tier"] > c["tier"]
                for x in s["containers"]
            )
            and not any(
                j["status"] != "completed"
                and (
                    j["container_id"] == c["id"]
                    or j["status"] == "running"
                    and c["location_id"] in (j["source_id"], j["target_id"])
                )
                for j in s["jobs"]
            )
        ]
        if not covers:
            raise RuleError("No uncommitted accessible cover available in this profile")
        cover = min(covers, key=lambda c: c["id"])
        old = cover["location_id"]
        cover.update(
            location_id=loc["id"],
            tier=max(
                c["tier"] for c in s["containers"] if c["location_id"] == loc["id"]
            )
            + 1,
        )
        if s.get("movement"):
            cover["custody"] = dict(kind="location", id=loc["id"])
        events.append(
            dict(
                kind="scenario.cover_injected",
                entity_id=cover["id"],
                message=f"Synthetic observation: {cover['id']} moved from {old} above {cargo['id']} at {loc['id']}; no real equipment command",
                affected_container=cargo["id"],
            )
        )
    elif action in ("close_route", "open_route"):
        if not s.get("movement"):
            raise RuleError("This run has no metric route network")
        edge = by_id(s["movement"]["edges"], command["entity_id"])
        if not edge:
            raise RuleError("Unknown route edge")
        edge["closed"] = action == "close_route"
        events.append(
            dict(
                kind="input.applied",
                entity_id=edge["id"],
                source="scenario-admin",
                message=f"Synthetic route observation: {edge['id']} {'closed' if edge['closed'] else 'open'}",
            )
        )
        if s.get("schedule"):
            from .schedule_execution import interrupt

            interrupt(s, events, "Route availability changed; inspect remaining work")
    elif action in ("fail", "repair"):
        e = by_id(s["equipment"], command["entity_id"])
        if not e:
            raise RuleError("Equipment not found")
        e["status"] = "failed" if action == "fail" else "available"
    elif action == "dispatch":
        j = by_id(s["jobs"], command["entity_id"])
        if not j or j["status"] != "queued":
            raise RuleError("Only queued work may dispatch")
        dispatch(s, j)
    elif action == "release":
        c = by_id(s["containers"], command["entity_id"])
        if not c:
            raise RuleError("Container not found")
        c.update(
            released=command["released"],
            hold_reason=None if command["released"] else "Synthetic authority hold",
        )
    elif action == "approve_plan":
        apply_policy(s, command["policy"])
        s["plan_id"] = command["plan_id"]
    elif action == "correct":
        e = by_id(s["equipment"], command["entity_id"])
        if not e:
            raise RuleError("Equipment not found")
        if command["valid_minute"] > s["minute"]:
            raise RuleError("Cannot observe a future event")
        # Correction updates current availability only if it is the latest valid-time observation.
        prior = [o for o in s["observations"] if o["entity_id"] == e["id"]]
        if not prior or command["valid_minute"] >= max(
            o["valid_minute"] for o in prior
        ):
            e["status"] = command["value"]
        same_time = [o for o in prior if o["valid_minute"] == command["valid_minute"]]
        s["observations"].append(
            dict(
                entity_id=e["id"],
                valid_minute=command["valid_minute"],
                recorded_minute=s["minute"],
                value=command["value"],
                revision=s["revision"] + 1,
                source="scenario-admin",
                supersedes=same_time[-1]["revision"] if same_time else None,
            )
        )
    else:
        raise RuleError("Unknown action")
    if action in ("fail", "repair"):
        s["observations"].append(
            dict(
                entity_id=command["entity_id"],
                valid_minute=s["minute"],
                recorded_minute=s["minute"],
                value="failed" if action == "fail" else "available",
                revision=s["revision"] + 1,
                source="scenario-admin",
                supersedes=None,
            )
        )
    if s.get("schedule") and action in (
        "fail",
        "repair",
        "release",
        "correct",
        "obstruct",
    ):
        from .schedule_execution import interrupt

        interrupt(
            s,
            events,
            "Operational input changed after approval; compare against the new evidence",
        )
    s["revision"] += 1
    events.append(
        dict(
            kind=f"command.{action}",
            entity_id=command.get("entity_id", "terminal"),
            message=f'{action.replace("_"," ")} accepted',
            valid_minute=(
                command["valid_minute"] if action == "correct" else s["minute"]
            ),
        )
    )
    validate(s)
    return s, events


def metrics(s):
    active = [c for c in s["containers"] if c["commitment_id"]]
    final = {
        c["id"]: max(
            [
                j
                for j in s["jobs"]
                if j["container_id"] == c["id"] and j["kind"] != "rehandle"
            ],
            key=lambda j: j["created_order"],
        )
        for c in active
    }
    ontime = sum(
        j["status"] == "completed" and j["completed_at"] <= j["deadline"]
        for j in final.values()
    )
    missed = sum(
        (j["status"] == "completed" and j["completed_at"] > j["deadline"])
        or (j["status"] != "completed" and s["minute"] > j["deadline"])
        for j in final.values()
    )
    return dict(
        total=len(active),
        on_time=ontime,
        missed=missed,
        pending=len(active) - ontime - missed,
        completed_moves=sum(j["status"] == "completed" for j in s["jobs"]),
        rehandles=sum(
            j["kind"] == "rehandle" and j["status"] == "completed" for j in s["jobs"]
        ),
        travel_minutes=sum(
            (
                sum(
                    p["end"] - p["start"]
                    for p in j.get("movement_stages", [])
                    if p.get("route")
                )
                if s.get("movement")
                else j["travel_minutes"]
            )
            for j in s["jobs"]
            if j["status"] == "completed"
        ),
        mean_wait=round(
            sum(
                (j["started_at"] if j["started_at"] is not None else s["minute"])
                for j in s["jobs"]
            )
            / len(s["jobs"]),
            1,
        ),
        lateness=sum(
            max(
                0,
                (j["completed_at"] if j["status"] == "completed" else s["minute"])
                - j["deadline"],
            )
            for j in final.values()
        ),
    )


def enrich(s):
    result = deepcopy(s)
    result["metrics"] = metrics(s)
    from .relationships import project, describe

    result["relationships"] = project(s)
    for equipment in result["equipment"]:
        equipment["within_shift"] = within_shift(s, equipment["id"])
    result["provenance"] = dict(
        mode=s.get("data_mode", "synthetic"),
        source=(
            f"Input pack: {s['dataset']['title']}; synthetic execution"
            if s.get("dataset")
            else "synthetic simulator"
        ),
        recorded_revision=s["revision"],
        observed_minute=s["minute"],
        resource_model=s.get("resource_model", "legacy-v1"),
        warning="Positions are simulated observations. Plans and predictions are separate; no terminal feed is connected.",
    )
    # Historical snapshots and relational reads have the same presentation order.
    for key in ("locations", "equipment", "containers", "jobs", "commitments"):
        result[key].sort(key=lambda row: row["id"])
    for j in result["jobs"]:
        j.update(describe(s, j))
        j["blockers"] = blockers(s, j)
        estimate = j["duration"]
        if s.get("movement") and j["status"] == "queued":
            from .movement import make_row

            ids = allocate(s, j, ignore_busy=True)
            try:
                if not ids:
                    raise RuleError(
                        "No compatible equipment available for a movement estimate"
                    )
                preview = make_row(s, j, s["minute"] + 1, ids)
                j["movement_preview"] = preview
                estimate = preview["end"] - preview["start"]
            except RuleError as exc:
                j["movement_error"] = str(exc)
        j["slack"] = j["deadline"] - s["minute"] - estimate
        j["risk"] = (
            "complete"
            if j["status"] == "completed"
            else (
                "missed"
                if s["minute"] > j["deadline"]
                else (
                    "blocked"
                    if j["blockers"]
                    else "tight" if j["slack"] < 15 else "ready"
                )
            )
        )
    return result


def simulate(snapshot, policy, seed, horizon=180, reassign=True):
    s = deepcopy(snapshot)
    s["seed"] = seed
    curve = []
    if reassign:
        apply_policy(s, policy)
    until = s["minute"] + horizon
    while s["minute"] < until:
        s, _ = tick(s)
        if s["minute"] % 5 == 0:
            curve.append(dict(minute=s["minute"], **metrics(s)))
    return dict(metrics=metrics(s), curve=curve, final_minute=s["minute"])
