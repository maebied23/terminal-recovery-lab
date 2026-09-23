"""Stage scheduling with position continuity and independent transition replay.

CP-SAT searches a bounded pool of physically generated timing/assignment options.
An optimum is scoped to that pool, never to all terminal schedules.
"""

from copy import deepcopy
import json
import time
from .domain import RuleError, by_id, dispatch, tick, ordered_jobs, blockers
from .movement import make_row, intervals, calendar_ok, conflict


def frozen(s):
    return [
        make_row(s, j, s["minute"], j["assigned_resources"], True)
        for j in s["jobs"]
        if j["status"] == "running"
    ]


def point_conflict(r, rows):
    def window(x):
        p = next((p for p in x["stages"] if p["kind"] == "transfer"), x["stages"][0])
        return p["start"], x["end"]

    a, b = window(r)
    return any(
        r["target_id"] == x["target_id"] and a < window(x)[1] and window(x)[0] < b
        for x in rows
    )


def greedy(snapshot, horizon, assigned=False, policy=None):
    from .scheduling import bundles

    s = deepcopy(snapshot)
    s.pop("schedule", None)
    s["policy"] = policy or (s["policy"] if assigned else "deadline")
    rows = frozen(s)

    def choose(current, events):
        for j in ordered_jobs(current):
            original = j["equipment_id"]
            for ids in bundles(current, j, assigned):
                j["equipment_id"] = ids[0]
                if blockers(current, j):
                    continue
                try:
                    r = make_row(current, j, current["minute"], ids)
                    if (
                        r["end"] > horizon
                        or not calendar_ok(current, r)
                        or conflict(r, rows)
                        or point_conflict(r, rows)
                    ):
                        continue
                    dispatch(current, j, ids)
                    rows.append(r)
                    break
                except RuleError:
                    continue
            else:
                j["equipment_id"] = original

    while s["minute"] < horizon:
        s, _ = tick(s, dispatch_hook=choose)
    # Physical completion is mandatory. No attractive timing-only result survives.
    if any(by_id(s["jobs"], r["job_id"])["completed_at"] != r["end"] for r in rows):
        raise RuleError(
            "Stage plan encountered an unresolved handover: "
            + str(
                [
                    (
                        r["job_id"],
                        r["end"],
                        by_id(s["jobs"], r["job_id"])["completed_at"],
                        by_id(s["jobs"], r["job_id"]).get("waiting_reason"),
                    )
                    for r in rows
                    if by_id(s["jobs"], r["job_id"])["completed_at"] != r["end"]
                ]
            )
        )
    return rows


def replay(snapshot, rows, horizon):
    from .scheduling import bundles

    s = deepcopy(snapshot)
    s.pop("schedule", None)
    if len({r["job_id"] for r in rows}) != len(rows):
        raise RuleError("Duplicate stage job")
    fixed = {r["job_id"]: r for r in frozen(s)}
    if fixed != {r["job_id"]: r for r in rows if r["frozen"]}:
        raise RuleError("In-progress custody/stages changed")
    previous = []
    for r in rows:
        if (
            not s["minute"] <= r["start"] < r["end"] <= horizon
            or conflict(r, previous)
            or point_conflict(r, previous)
        ):
            raise RuleError("Stage resource / transfer-point overlap or invalid bounds")
        if not r["frozen"] and not calendar_ok(s, r):
            raise RuleError("Stage calendar violation")
        previous.append(r)

    def execute(current, events):
        for r in sorted(rows, key=lambda r: (r["start"], r["job_id"])):
            if r["frozen"] or r["start"] != current["minute"]:
                continue
            j = by_id(current["jobs"], r["job_id"])
            if not j or j["status"] != "queued":
                raise RuleError("Invalid stage job status")
            j["equipment_id"] = r["resources"][0]
            if (
                r["resources"] not in bundles(current, j)
                or make_row(current, j, r["start"], r["resources"]) != r
            ):
                raise RuleError("Route, tractor position or stage evidence changed")
            dispatch(current, j, r["resources"])

    while s["minute"] < horizon:
        s, _ = tick(s, dispatch_hook=execute)
    for r in rows:
        j = by_id(s["jobs"], r["job_id"])
        if j["status"] != "completed" or j["completed_at"] != r["end"]:
            raise RuleError("Stage replay did not complete the proposed handovers")
    return s


def dispatch_conflict(r, t):
    """Dispatch requires the assigned bundle free now, even before a later stage.

    This guard mirrors domain.dispatch without reserving unused equipment for
    the full move. Real stage intervals remain the capacity model.
    """
    return any(e in r["resources"] and a <= r["start"] < b for e, a, b in intervals(t))


def constraint_schedule(s, horizon, seconds=4):
    from ortools.sat.python import cp_model

    started = time.monotonic()
    from .scheduling import outcomes

    pools = [
        greedy(s, horizon, policy=p)
        for p in ("deadline", "fifo", "rail-first", "vessel-first")
    ]
    fixed = frozen(s)
    options = {}
    for rows in pools:
        for r in rows:
            if not r["frozen"]:
                options[json.dumps(r, sort_keys=True)] = r
    m = cp_model.CpModel()
    choices = []
    equipment = {}
    jobs = {}
    for i, r in enumerate(options.values()):
        present = m.new_bool_var(f"option:{i}")
        choices.append((present, r))
        jobs.setdefault(r["job_id"], []).append((present, r))
        for eid, a, b in intervals(r):
            equipment.setdefault(eid, []).append(
                m.new_optional_fixed_size_interval_var(
                    a, b - a, present, f"{i}:{eid}:{a}"
                )
            )
    for r in fixed:
        for eid, a, b in intervals(r):
            equipment.setdefault(eid, []).append(
                m.new_fixed_size_interval_var(a, b - a, f"frozen:{eid}:{a}")
            )
    # Each tractor follows a single chronological path through selected options.
    # An arc is legal only when the next empty leg starts at the preceding drop.
    for tractor in [e for e in s["equipment"] if e["kind"] == "tractor"]:
        opts = [(p, r) for p, r in choices if tractor["id"] in r["resources"]]
        arcs = []
        idle = m.new_bool_var("unused:" + tractor["id"])
        arcs.append((0, 0, idle))
        m.add(sum(p for p, r in opts) == 0).only_enforce_if(idle)
        m.add(sum(p for p, r in opts) >= 1).only_enforce_if(idle.Not())
        for i, (p, r) in enumerate(opts, 1):
            arcs.append((i, i, p.Not()))
            empty = next(
                (x["route"] for x in r["stages"] if x["kind"] == "empty"), None
            )
            initial = tractor.get("node_id")
            preceding = next(
                (x for x in fixed if tractor["id"] in x["resources"]), None
            )
            if preceding:
                initial = preceding["target_id"]
            origin = empty["source"] if empty else r["source_id"]
            if origin == initial and (not preceding or preceding["end"] <= r["start"]):
                arcs.append((0, i, m.new_bool_var(f'{tractor["id"]}:first:{i}')))
            arcs.append((i, 0, m.new_bool_var(f'{tractor["id"]}:last:{i}')))
            for k, (q, t) in enumerate(opts, 1):
                next_empty = next(
                    (x["route"] for x in t["stages"] if x["kind"] == "empty"), None
                )
                next_origin = next_empty["source"] if next_empty else t["source_id"]
                if r["end"] <= t["start"] and r["target_id"] == next_origin:
                    arcs.append((i, k, m.new_bool_var(f'{tractor["id"]}:{i}>{k}')))
        m.add_circuit(arcs)
    for i, (p, r) in enumerate(choices):
        for q, t in choices[i + 1 :]:
            if (
                point_conflict(r, [t])
                or dispatch_conflict(r, t)
                or dispatch_conflict(t, r)
            ):
                m.add(p + q <= 1)
    for p, r in choices:
        if any(dispatch_conflict(r, t) for t in fixed):
            m.add(p == 0)
    for v in equipment.values():
        m.add_no_overlap(v)
    for opts in jobs.values():
        m.add(sum(p for p, _ in opts) <= 1)
    ends = {r["job_id"]: r["end"] for r in fixed}
    for p, r in choices:
        for dep in by_id(s["jobs"], r["job_id"])["dependencies"]:
            if by_id(s["jobs"], dep)["status"] == "completed":
                continue
            if dep in ends:
                if ends[dep] > r["start"]:
                    m.add(p == 0)
            else:
                m.add(
                    p <= sum(q for q, t in jobs.get(dep, []) if t["end"] <= r["start"])
                )
    # Unique final visits drive the objective; optional precursor moves are not cargo throughput.
    gain = []
    for p, r in choices:
        j = by_id(s["jobs"], r["job_id"])
        c = by_id(s["containers"], r["container_id"])
        co = by_id(s["commitments"], c["commitment_id"])
        if co and j["kind"] != "rehandle" and j["target_id"] == co["location_id"]:
            gain.append(
                p
                * (
                    (1 + len(s["jobs"]) * horizon) * (r["end"] <= co["cutoff"])
                    + max(0, horizon - r["end"])
                )
            )
    m.maximize(sum(gain))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_search_workers = 1
    status = solver.solve(m)
    name = solver.status_name(status)
    result = [
        *fixed,
        *[
            r
            for p, r in choices
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and solver.value(p)
        ],
    ]
    report = dict(
        engine="CP-SAT stage options",
        elapsed_seconds=round(time.monotonic() - started, 3),
        passes=[],
        status=name,
        scope="Bounded stage-option pool; on-time visits then completion time",
        options=len(choices),
        seconds=seconds,
    )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, report
    try:
        replay(s, result, horizon)
    except RuleError as exc:
        # Do not silently relabel a heuristic fallback as solver output.
        report.update(status="REJECTED", reason=str(exc))
        return None, report
    return result, report
