"""Bounded recovery planning: explicit bookings, pure generation and independent replay.

Whole-move resource bundles deliberately over-reserve handlers. Stage timing is
an explanatory partition, not a claim of independently calibrated handovers.
"""

from copy import deepcopy
from itertools import product
import math
import time
from .domain import (
    RuleError,
    by_id,
    eligible_equipment,
    requirements,
    blockers,
    dispatch,
    tick,
    validate,
    ordered_jobs,
)

VERSION = "bundle-scheduler-v1"


def budget(s, j):
    return max(
        3,
        math.ceil(j["duration"] * s.get("duration_factor", 1) * 1.2)
        + j.get("travel_minutes", 1),
    )


def windows(s, resources, lower, upper, length):
    """Intersect full-duration calendars, not merely dispatch availability."""
    spans = [(lower, upper)]
    for eid in resources:
        choices = [
            (w["start_minute"], w["end_minute"] - length)
            for w in s.get("availability", [])
            if w["equipment_id"] == eid
        ]
        if "availability" not in s:
            choices = [(lower, upper)]
        spans = [
            (max(a, c), min(b, d))
            for a, b in spans
            for c, d in choices
            if max(a, c) <= min(b, d)
        ]
    return sorted(set(spans))


def bundles(s, j, assigned=False):
    cargo = by_id(s["containers"], j["container_id"])
    result = []
    for primary in eligible_equipment(s, j):
        if assigned and primary["id"] != j["equipment_id"]:
            continue
        trial = dict(j, equipment_id=primary["id"])
        choices = []
        for r in requirements(s, trial):
            choices.append(
                [
                    eid
                    for eid in ([r["assigned"]] if r["assigned"] else r["eligible"])
                    if by_id(s["equipment"], eid)["status"] == "available"
                    and (
                        by_id(s["equipment"], eid)["kind"] not in ("yard", "quay")
                        or cargo["weight_t"]
                        <= by_id(s["equipment"], eid).get("lifting_capacity_t", 50)
                    )
                ]
            )
        for ids in product(*choices):
            if len(ids) == len(set(ids)):
                result.append(list(ids))
    return result


def row(s, j, start, resources, frozen=False):
    if s.get("movement"):
        from .movement import make_row

        return make_row(s, j, start, resources, frozen)
    end = start + (j["remaining"] if frozen else budget(s, j))
    if frozen:
        stages = [dict(name="Finish in-progress move", start=start, end=end)]
    else:
        travel = max(1, min(j.get("travel_minutes", 1), end - start - 2))
        pickup = max(1, (end - start - travel) // 2)
        stages = [
            dict(name="Pickup", start=start, end=start + pickup),
            dict(name="Transfer", start=start + pickup, end=start + pickup + travel),
            dict(name="Set down", start=start + pickup + travel, end=end),
        ]
    return dict(
        job_id=j["id"],
        container_id=j["container_id"],
        visit_id=by_id(s["containers"], j["container_id"])["visit_id"],
        source_id=j["source_id"],
        target_id=j["target_id"],
        start=start,
        end=end,
        resources=resources,
        stages=stages,
        frozen=frozen,
    )


def service_bounds(s, j, horizon):
    lo, hi = s["minute"] + 1, horizon - budget(s, j)
    cargo = by_id(s["containers"], j["container_id"])
    co = by_id(s["commitments"], cargo["commitment_id"])
    if co and j["kind"] in ("retrieve", "load"):
        lo, hi = max(lo, co["arrival"]), min(hi, co["cutoff"])
        if co["status"] == "departed":
            hi = -1
    source = next(
        (c for c in s["commitments"] if c["location_id"] == j["source_id"]), None
    )
    if source and j["kind"] == "discharge":
        lo, hi = max(lo, source["arrival"]), min(hi, source["cutoff"])
    return lo, hi


def initial_rows(s):
    if s.get("movement"):
        from .stage_planning import frozen

        return frozen(s)
    return [
        row(s, j, s["minute"], list(j["resources"]), True)
        for j in s["jobs"]
        if j["status"] == "running"
    ]


def greedy(snapshot, horizon, assigned=False):
    if snapshot.get("movement"):
        from .stage_planning import greedy as staged

        return staged(snapshot, horizon, assigned)
    """Feasible earliest-deadline list scheduling, including background demand."""
    s = deepcopy(snapshot)
    s.pop("schedule", None)
    if not assigned:
        s["policy"] = "deadline"
    rows = initial_rows(s)

    def choose(current, events):
        for j in ordered_jobs(current):
            lo, hi = service_bounds(snapshot, j, horizon)
            if not lo <= current["minute"] <= hi:
                continue
            original = j["equipment_id"]
            for ids in bundles(current, j, assigned):
                if any(by_id(current["equipment"], e)["job_id"] for e in ids):
                    continue
                if not windows(
                    current,
                    ids,
                    current["minute"],
                    current["minute"],
                    budget(current, j),
                ):
                    continue
                j["equipment_id"] = ids[0]
                if blockers(current, j):
                    continue
                r = row(current, j, current["minute"], ids)
                dispatch(current, j, ids)
                j["remaining"] = r["end"] - r["start"]
                rows.append(r)
                break
            else:
                j["equipment_id"] = original

    while s["minute"] < horizon:
        s, _ = tick(s, dispatch_hook=choose)
    return rows


def outcomes(s, rows, horizon):
    ends = {r["job_id"]: r["end"] for r in rows}
    visits = []
    for cargo in s["containers"]:
        co = by_id(s["commitments"], cargo["commitment_id"])
        if not co:
            continue
        finals = [
            j
            for j in s["jobs"]
            if j["container_id"] == cargo["id"]
            and j["target_id"] == co["location_id"]
            and j["kind"] != "rehandle"
        ]
        final = finals[0] if len(finals) == 1 else None
        end = (
            final.get("completed_at")
            if final and final["status"] == "completed"
            else ends.get(final["id"]) if final else None
        )
        visits.append(
            dict(
                container_id=cargo["id"],
                visit_id=cargo["visit_id"],
                commitment_id=co["id"],
                cutoff=co["cutoff"],
                completion=end,
                on_time=end is not None and end <= co["cutoff"],
                lateness=max(0, (end if end is not None else horizon) - co["cutoff"]),
            )
        )
    services = []
    for co in s["commitments"]:
        group = [v for v in visits if v["commitment_id"] == co["id"]]
        services.append(
            dict(
                id=co["id"],
                total=len(group),
                on_time=sum(v["on_time"] for v in group),
                unscheduled=sum(v["completion"] is None for v in group),
                lateness=sum(v["lateness"] for v in group),
                cutoff=co["cutoff"],
            )
        )
    jobs = {j["id"]: j for j in s["jobs"]}
    metrics = dict(
        missed=sum(not v["on_time"] for v in visits),
        lateness=sum(v["lateness"] for v in visits),
        rehandles=sum(
            jobs[r["job_id"]]["kind"] == "rehandle" for r in rows if not r["frozen"]
        ),
        travel=sum(
            (
                sum(p["end"] - p["start"] for p in r["stages"] if p.get("route"))
                if s.get("movement")
                else jobs[r["job_id"]].get("travel_minutes", 1)
            )
            for r in rows
            if not r["frozen"]
        ),
        changes=sum(
            r["resources"][0] != jobs[r["job_id"]]["equipment_id"]
            for r in rows
            if not r["frozen"]
        ),
    )
    return dict(visits=visits, services=services, metrics=metrics)


def replay(snapshot, rows, horizon):
    if snapshot.get("movement"):
        from .stage_planning import replay as staged

        return staged(snapshot, rows, horizon)
    """Independent physical validation, never trusting solver feasibility alone."""
    s = deepcopy(snapshot)
    s.pop("schedule", None)
    ids = [r["job_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise RuleError("Duplicate scheduled job")
    frozen = {r["job_id"]: r for r in initial_rows(s)}
    bookings = {}
    for r in rows:
        j = by_id(s["jobs"], r["job_id"])
        if not j or j["status"] == "completed":
            raise RuleError("Unknown or already completed scheduled work")
        if r["frozen"]:
            if r != frozen.get(r["job_id"]):
                raise RuleError("In-progress work cannot be changed")
        else:
            expected = row(s, j, r["start"], r["resources"])
            if r != expected or not s["minute"] < r["start"] < r["end"] <= horizon:
                raise RuleError("Schedule identity, duration or stage bounds invalid")
            if r["resources"] not in bundles(s, j):
                raise RuleError("Incompatible equipment bundle")
            if not windows(
                s, r["resources"], r["start"], r["start"], r["end"] - r["start"]
            ):
                raise RuleError("Reservation exceeds equipment availability")
        for eid in r["resources"]:
            if any(
                r["start"] < end and start < r["end"]
                for start, end in bookings.get(eid, [])
            ):
                raise RuleError("Equipment booking overlaps")
            bookings.setdefault(eid, []).append((r["start"], r["end"]))
    if set(frozen) != {r["job_id"] for r in rows if r["frozen"]}:
        raise RuleError("In-progress work omitted")

    def execute(current, events):
        for r in sorted(rows, key=lambda r: (r["start"], r["job_id"])):
            if r["frozen"] or r["start"] != current["minute"]:
                continue
            j = by_id(current["jobs"], r["job_id"])
            j["equipment_id"] = r["resources"][0]
            dispatch(current, j, r["resources"])
            j["remaining"] = r["end"] - r["start"]

    while s["minute"] < horizon:
        s, _ = tick(s, dispatch_hook=execute)
    for r in rows:
        j = by_id(s["jobs"], r["job_id"])
        if j["status"] != "completed" or j["completed_at"] != r["end"]:
            raise RuleError("Replay did not complete a booked move as projected")
    validate(s)
    return s


def solver_status(reports, has_incumbent, objective_count):
    """An optimum for one priority is not an optimum for the whole objective."""
    if has_incumbent:
        return (
            "OPTIMAL"
            if len(reports) == objective_count
            and all(r["status"] == "OPTIMAL" for r in reports)
            else "FEASIBLE"
        )
    return reports[-1]["status"] if reports else "UNKNOWN"


def constraint_schedule(s, horizon, seconds=4):
    if s.get("movement"):
        from .stage_planning import constraint_schedule as staged

        return staged(s, horizon, seconds)
    """Optional synchronized intervals. Physical replay is a separate acceptance gate.

    The CP model includes precedence, conservative stack access, capacity, holds, full
    calendars, source sequences and frozen resources. Independent replay verifies the
    physical state transitions; solver status refers only to this bounded model.
    """
    import ortools
    from ortools.sat.python import cp_model

    m = cp_model.CpModel()
    base = s["minute"]
    tasks, resource_intervals = {}, {e["id"]: [] for e in s["equipment"]}
    frozen = initial_rows(s)
    for r in frozen:
        for eid in r["resources"]:
            resource_intervals[eid].append(
                m.new_fixed_size_interval_var(
                    base, r["end"] - base, f"frozen:{r['job_id']}:{eid}"
                )
            )
    for j in s["jobs"]:
        if j["status"] != "queued":
            continue
        d = budget(s, j)
        present = m.new_bool_var(j["id"] + " present")
        start = m.new_int_var(base + 1, horizon, j["id"] + " start")
        end = m.new_int_var(base + 1, horizon + d, j["id"] + " end")
        m.add(end == start + d)
        opts = []
        lo, hi = service_bounds(s, j, horizon)
        cargo = by_id(s["containers"], j["container_id"])
        for ids in bundles(s, j):
            for a, b in windows(s, ids, lo, hi, d):
                p = m.new_bool_var(f"{j['id']}:{ids}:{a}")
                m.add(start >= a).only_enforce_if(p)
                m.add(start <= b).only_enforce_if(p)
                interval = m.new_optional_interval_var(start, d, end, p, str(ids))
                for eid in ids:
                    resource_intervals[eid].append(interval)
                opts.append((p, ids))
        m.add(sum(p for p, _ in opts) == present)
        if j["release_required"] and not cargo["released"]:
            m.add(present == 0)
        tasks[j["id"]] = dict(j=j, p=present, start=start, end=end, opts=opts)
    for intervals in resource_intervals.values():
        m.add_no_overlap(intervals)
    frozen_ends = {r["job_id"]: r["end"] for r in frozen}

    def before(a, b):
        if a in tasks:
            m.add(b["p"] <= tasks[a]["p"])
            m.add(b["start"] >= tasks[a]["end"]).only_enforce_if(b["p"])
        elif a in frozen_ends:
            m.add(b["start"] >= frozen_ends[a]).only_enforce_if(b["p"])

    for t in tasks.values():
        j = t["j"]
        for dep in j["dependencies"]:
            before(dep, t)
        cargo = by_id(s["containers"], j["container_id"])
        # Access relocations may be created AFTER the onward instruction. Use declared ancestry first.
        ancestry = set()

        def walk(jid):
            for dep in by_id(s["jobs"], jid)["dependencies"]:
                if dep not in ancestry:
                    ancestry.add(dep)
                    walk(dep)

        walk(j["id"])
        transfers = [
            k
            for k in s["jobs"]
            if k["id"] in ancestry
            and k["container_id"] == cargo["id"]
            and k["status"] != "completed"
            and k["target_id"] == j["source_id"]
        ]
        if cargo["location_id"] != j["source_id"] and not transfers:
            m.add(t["p"] == 0)
        if cargo["location_id"] == j["source_id"]:
            for cover in s["containers"]:
                if (
                    cover["location_id"] == cargo["location_id"]
                    and cover["tier"] > cargo["tier"]
                    and by_id(s["locations"], cargo["location_id"])["kind"] == "yard"
                ):
                    departures = [
                        k
                        for k in s["jobs"]
                        if k["container_id"] == cover["id"]
                        and k["source_id"] == cargo["location_id"]
                        and k["status"] == "queued"
                    ]
                    if len(departures) == 1:
                        before(departures[0]["id"], t)
                    else:
                        m.add(t["p"] == 0)
    # Capacity includes space committed to in-flight placement. A conservative
    # access lane serializes incoming active visits at each stack: avoid relying
    # on an unmodeled LIFO rearrangement to make an attractive timetable feasible.
    for loc in s["locations"]:
        intervals = []
        incoming_lanes = []
        initial_departures = []
        for cargo in s["containers"]:
            if cargo["location_id"] != loc["id"]:
                continue
            exits = [
                t
                for t in tasks.values()
                if t["j"]["container_id"] == cargo["id"]
                and t["j"]["source_id"] == loc["id"]
            ]
            exit_task = (
                min(exits, key=lambda t: t["j"]["created_order"]) if exits else None
            )
            leave = m.new_int_var(base, horizon, cargo["id"] + " initial leave")
            if exit_task:
                m.add(leave == exit_task["start"]).only_enforce_if(exit_task["p"])
                m.add(leave == horizon).only_enforce_if(exit_task["p"].Not())
                initial_departures.append(exit_task)
            else:
                m.add(leave == horizon)
            length = m.new_int_var(0, horizon - base, "initial occupancy")
            m.add(length == leave - base)
            intervals.append(m.new_interval_var(base, length, leave, "initial slot"))
        for t in tasks.values():
            if t["j"]["target_id"] != loc["id"]:
                continue
            exits = [
                u
                for u in tasks.values()
                if u["j"]["container_id"] == t["j"]["container_id"]
                and u["j"]["source_id"] == loc["id"]
                and u is not t
            ]
            onward = (
                min(exits, key=lambda u: u["j"]["created_order"]) if exits else None
            )
            leave = m.new_int_var(base, horizon, "target leave")
            if onward:
                m.add(leave == onward["start"]).only_enforce_if(onward["p"])
                m.add(leave == horizon).only_enforce_if(onward["p"].Not())
                before(t["j"]["id"], onward)
            else:
                m.add(leave == horizon)
            length = m.new_int_var(0, horizon - base, "reserved slot duration")
            m.add(length == leave - t["start"]).only_enforce_if(t["p"])
            occupied = m.new_optional_interval_var(
                t["start"], length, leave, t["p"], "reserved slot"
            )
            intervals.append(occupied)
            if loc["kind"] == "yard":
                incoming_lanes.append(occupied)
                for departure in initial_departures:
                    # Deliveries may not cover an initial active pickup. This is
                    # a conservative model restriction, not a universal TOS rule.
                    m.add(departure["p"] >= t["p"])
                    m.add(t["start"] >= departure["end"]).only_enforce_if(t["p"])
        for r in frozen:
            if r["target_id"] == loc["id"]:
                # Existing lifts own destination capacity until onward pickup.
                exits = [
                    t
                    for t in tasks.values()
                    if t["j"]["container_id"] == r["container_id"]
                    and t["j"]["source_id"] == loc["id"]
                ]
                onward = (
                    min(exits, key=lambda u: u["j"]["created_order"]) if exits else None
                )
                leave = m.new_int_var(base, horizon, "frozen destination leave")
                if onward:
                    m.add(leave == onward["start"]).only_enforce_if(onward["p"])
                    m.add(leave == horizon).only_enforce_if(onward["p"].Not())
                else:
                    m.add(leave == horizon)
                length = m.new_int_var(0, horizon - base, "frozen slot")
                m.add(length == leave - base)
                occupied = m.new_interval_var(base, length, leave, "frozen slot")
                intervals.append(occupied)
                if loc["kind"] == "yard":
                    incoming_lanes.append(occupied)
        if intervals:
            m.add_cumulative(intervals, [1] * len(intervals), loc["capacity"])
        if incoming_lanes:
            m.add_no_overlap(incoming_lanes)
    missed, late, moves, changes = [], [], [], []
    for cargo in s["containers"]:
        co = by_id(s["commitments"], cargo["commitment_id"])
        if not co:
            continue
        finals = [
            t
            for t in tasks.values()
            if t["j"]["container_id"] == cargo["id"]
            and t["j"]["target_id"] == co["location_id"]
            and t["j"]["kind"] != "rehandle"
        ]
        if len(finals) != 1:
            continue
        t = finals[0]
        ontime = m.new_bool_var(cargo["id"] + " ontime")
        m.add(ontime <= t["p"])
        m.add(t["end"] <= co["cutoff"]).only_enforce_if(ontime)
        missed.append(1 - ontime)
        penalty = m.new_int_var(0, horizon + 50, cargo["id"] + " late")
        m.add(penalty >= t["end"] - co["cutoff"]).only_enforce_if(t["p"])
        m.add(penalty == max(0, horizon - co["cutoff"])).only_enforce_if(t["p"].Not())
        late.append(penalty)
    for t in tasks.values():
        if t["j"]["kind"] == "rehandle":
            moves.append(t["p"])
        changes.extend(p for p, ids in t["opts"] if ids[0] != t["j"]["equipment_id"])
    objectives = [
        ("missed scheduled obligations", sum(missed)),
        ("censored lateness", sum(late)),
        ("relocations", sum(moves)),
        (
            "transfer minutes",
            sum(t["p"] * t["j"].get("travel_minutes", 1) for t in tasks.values()),
        ),
        ("assignment changes", sum(changes)),
    ]
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 42
    started = time.monotonic()
    reports, result = [], None
    for name, objective in objectives:
        remaining = seconds - (time.monotonic() - started)
        if remaining <= 0:
            break
        solver.parameters.max_time_in_seconds = remaining
        m.minimize(objective)
        status = solver.solve(m)
        reports.append(
            dict(
                objective=name,
                status=solver.status_name(status),
                value=(
                    solver.objective_value
                    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
                    else None
                ),
                bound=solver.best_objective_bound,
            )
        )
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break
        result = frozen + [
            row(
                s,
                t["j"],
                solver.value(t["start"]),
                next(ids for p, ids in t["opts"] if solver.boolean_value(p)),
            )
            for t in tasks.values()
            if solver.boolean_value(t["p"])
        ]
        if status != cp_model.OPTIMAL:
            break
        m.add(objective == round(solver.objective_value))
    incumbent_status = solver_status(reports, result is not None, len(objectives))
    return result, dict(
        engine="OR-Tools CP-SAT",
        version=ortools.__version__,
        budget_seconds=seconds,
        elapsed_seconds=round(time.monotonic() - started, 3),
        passes=reports,
        status=incumbent_status,
        scope="Conservative stack-access model with capacity and synchronized bundles; independent replay still required",
    )


def build(snapshot, horizon=180, seconds=4):
    validate(snapshot)
    if snapshot.get("data_mode", "synthetic") != "synthetic":
        raise RuleError("Only the simulator adapter is implemented")
    if len(snapshot["jobs"]) > 120 or len(snapshot["equipment"]) > 30:
        raise RuleError("Laptop planner limit: 120 jobs and 30 equipment units")
    from .movement import unknown_completion

    if any(
        j["status"] == "running"
        and (blockers(snapshot, j) or unknown_completion(snapshot, j))
        for j in snapshot["jobs"]
    ):
        raise RuleError(
            "An in-progress move is paused by failed equipment. Resolve it before scheduling a known completion."
        )
    end = snapshot["minute"] + horizon
    candidates = []
    for key, title, assigned in [
        ("baseline", "Keep current assignments", True),
        ("deadline", "Earliest-deadline recovery", False),
    ]:
        existing = snapshot.get("schedule")
        if assigned and existing and existing["status"] in ("approved", "executing"):
            title = "Keep approved bookings"
            rows = initial_rows(snapshot) + [
                deepcopy(r)
                for r in existing["rows"]
                if by_id(snapshot["jobs"], r["job_id"])["status"] == "queued"
            ]
        else:
            rows = greedy(snapshot, end, assigned)
        try:
            replay(snapshot, rows, end)
            candidates.append(
                dict(
                    key=key,
                    title=title,
                    rows=rows,
                    validation="passed",
                    **outcomes(snapshot, rows, end),
                )
            )
        except RuleError as exc:
            candidates.append(
                dict(
                    key=key,
                    title=title,
                    rows=rows,
                    validation="rejected",
                    error=str(exc),
                )
            )
    rows, solver = constraint_schedule(snapshot, end, seconds)
    if rows is not None:
        try:
            replay(snapshot, rows, end)
            candidates.append(
                dict(
                    key="constraint",
                    title="Constraint-scheduled recovery",
                    rows=rows,
                    validation="passed",
                    **outcomes(snapshot, rows, end),
                )
            )
        except RuleError as exc:
            candidates.append(
                dict(
                    key="constraint",
                    title="Constraint-scheduled recovery",
                    rows=rows,
                    validation="rejected",
                    error=str(exc),
                )
            )
    else:
        candidates.append(
            dict(
                key="constraint",
                title="Constraint-scheduled recovery",
                rows=[],
                validation="rejected" if solver.get("reason") else "no solution",
                error=solver.get("reason")
                or "No incumbent within this solver budget; use a validated baseline.",
            )
        )
    feasible = [c for c in candidates if c["validation"] == "passed"]
    best = min(
        feasible,
        key=lambda c: tuple(
            c["metrics"][k]
            for k in ("missed", "lateness", "rehandles", "travel", "changes")
        ),
        default=None,
    )
    baseline = next((c for c in feasible if c["key"] == "baseline"), None)
    for c in feasible:
        c["impact"] = [
            dict(
                id=co["id"],
                on_time=co["on_time"],
                total=co["total"],
                delta=(
                    co["on_time"]
                    - next(
                        x["on_time"]
                        for x in baseline["services"]
                        if x["id"] == co["id"]
                    )
                    if baseline
                    else None
                ),
            )
            for co in c["services"]
        ]
        scheduled = {r["job_id"] for r in c["rows"]}
        c["unresolved"] = [
            dict(
                job_id=j["id"],
                container_id=j["container_id"],
                reasons=blockers(snapshot, j, ignore_busy=True)
                or ["Not selected within the horizon / resource competition"],
            )
            for j in snapshot["jobs"]
            if j["status"] == "queued" and j["id"] not in scheduled
        ]
    return dict(
        version=snapshot.get("movement", {}).get("version", VERSION),
        base_revision=snapshot["revision"],
        base_minute=snapshot["minute"],
        end_minute=end,
        recommended=best["key"] if best else None,
        candidates=candidates,
        solver=solver,
        assumptions=(
            [
                "Synthetic metric routes; explicit pickup/transfer/set-down with empty tractor travel.",
                "One receiving transfer point per destination; no traffic collision model.",
                "CP-SAT searches a bounded pool of stage options; physical replay can reject its result.",
                "All terminal work competes; no future input knowledge; missed cargo objective, not whole-service punctuality.",
            ]
            if snapshot.get("movement")
            else [
                "All terminal commitments and background jobs included; no future feed envelopes read.",
                "Handling budget = rounded-up base × 1.2 plus transfer; synthetic, not calibrated.",
                "Pickup / transfer / set-down share a conservative whole-move equipment reservation.",
                "Known holds and failed equipment stay unresolved; no invented release or repair.",
                "Rail loading uses the existing simplified yard handler; no train loading physics.",
                "Solver serializes incoming active visits at a stack; this can exclude useful real-world rearrangements.",
                "Unscheduled cargo counts as missed; lateness is censored at the horizon, not a predicted eventual delay.",
            ]
        ),
    )
