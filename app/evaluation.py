"""Pure evaluation: freeze plans before revealing paired execution disturbances.

No operational writes. Scenario families are versioned separately from the
planner. Holdout results are internal synthetic stress evidence, not external
validation; exposing them makes them regression cases for subsequent tuning.
"""

from copy import deepcopy
from hashlib import sha256
import json
import time
from pathlib import Path
from .domain import by_id, blockers, duration, tick, validate, RuleError
from .scheduling import build, outcomes
from .schedule_execution import activate
from .datasets import load_pack

SPEC = Path(__file__).resolve().parents[1] / "evaluation/scenarios.json"
STRATEGIES = ("baseline", "deadline", "constraint")


def digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def manifest():
    raw = json.loads(SPEC.read_text())
    raw["digest"] = digest(raw)
    raw["planner_digest"] = digest(
        {
            p: (SPEC.parents[1] / "app" / p).read_text()
            for p in (
                "scheduling.py",
                "domain.py",
                "schedule_execution.py",
                "evaluation.py",
            )
        }
    )
    raw["limitations"] = [
        "Synthetic stress families, not real-terminal validation or calibrated confidence.",
        "Holdout families were not used to tune step 4; once inspected they become regression evidence, not permanently unseen data.",
        "Paired per-job duration streams; plans generated once before execution seeds and future events are revealed.",
        "Delivered notices become effective at delivery; the physical world before a delayed notice is not modeled.",
        "Fixed plans with safe interruption. This does not evaluate automatic replanning or operator recovery skill.",
        "Small samples: report distributions and coverage, not statistical significance or operational ROI.",
    ]
    return raw


def scenario_state(spec):
    s = deepcopy(load_pack(spec["pack"])["state"])
    known = spec.get("known", {})
    if known.get("cutoff_factor"):
        for co in s["commitments"]:
            co["cutoff"] = max(
                co["arrival"] + 5, round(co["cutoff"] * known["cutoff_factor"])
            )
        for j in s["jobs"]:
            co = by_id(
                s["commitments"],
                by_id(s["containers"], j["container_id"])["commitment_id"],
            )
            if co:
                j["deadline"] = co["cutoff"]
    if known.get("split_calendars"):
        affected = known["split_calendars"]
        s["availability"] = [
            w for w in s["availability"] if w["equipment_id"] not in affected
        ]
        for eid in affected:
            s["availability"] += [
                dict(equipment_id=eid, start_minute=0, end_minute=15),
                dict(equipment_id=eid, start_minute=35, end_minute=180),
            ]
    if known.get("position_mismatch"):
        by_id(s["containers"], "CT-0122").update(location_id="A2", tier=5)
    validate(s)
    return s


def deliver(s, event):
    target = by_id(
        s["equipment"] if event["kind"] == "equipment.status" else s["containers"],
        event["entity_id"],
    )
    if event["kind"] == "equipment.status":
        target["status"] = event["value"]
    else:
        target.update(
            released=event["value"],
            hold_reason=None if event["value"] else "Evaluation hold",
        )
    validate(s)
    return dict(
        kind="input.applied",
        entity_id=event["entity_id"],
        valid_minute=event["observed_minute"],
        delivered_minute=s["minute"],
        source="evaluation fixture",
        message="Synthetic notice delivered",
        value=event["value"],
    )


def simulate_candidate(snapshot, candidate, scenario, seed, end):
    """Freeze the chosen schedule, then vary execution, never the prediction."""
    result = dict(
        strategy=candidate["key"],
        seed=seed,
        validation=candidate["validation"],
        predicted=candidate.get("metrics"),
        predicted_services=candidate.get("services", []),
        error=candidate.get("error"),
        execution_status="not_executable",
        observed=None,
        visits=[],
        services=[],
        events=[],
        jobs=[],
        rows=candidate.get("rows", []),
    )
    if candidate["validation"] != "passed":
        return result
    s = deepcopy(snapshot)
    plan = dict(
        id=f"evaluation:{candidate['key']}",
        base_revision=s["revision"],
        rows=candidate["rows"],
        end_minute=end,
        title=candidate["title"],
        projection=candidate["services"],
    )
    activate(s, plan, [])
    # Critical information boundary: perturb execution AFTER activation/replay.
    s["seed"] = seed
    s["duration_factor"] = scenario.get("duration_factor", 1.0)
    durations = {
        j["id"]: duration(seed, j, s["duration_factor"]) + j.get("travel_minutes", 1)
        for j in s["jobs"]
    }
    if s.get("movement"):
        durations = dict(
            model=s["movement"]["digest"],
            execution_factor=s["duration_factor"],
            seed=seed,
        )
        s["_execution_duration_factor"] = s["duration_factor"]
        s["duration_factor"] = snapshot.get("duration_factor", 1)
    result["duration_stream_digest"] = digest(durations)
    resource_wait = 0
    started = time.monotonic()
    events = []
    while s["minute"] < end:
        for j in s["jobs"]:
            if j["status"] != "queued":
                continue
            reasons = blockers(s, j)
            if reasons and all(
                any(
                    word in b
                    for word in (
                        "busy",
                        "unavailable",
                        "No free",
                        "availability",
                        "lifting limit",
                    )
                )
                for b in reasons
            ):
                resource_wait += 1

        def inputs(current):
            return [
                deliver(current, e)
                for e in scenario.get("events", [])
                if e["delivery_minute"] == current["minute"]
            ]

        s, ev = tick(s, before_tick=inputs)
        events.extend(ev)
    validate(s)
    observed = outcomes(s, [], end)
    initial_completed = {
        j["id"] for j in snapshot["jobs"] if j["status"] == "completed"
    }
    completed = [
        j
        for j in s["jobs"]
        if j["status"] == "completed" and j["id"] not in initial_completed
    ]
    services = observed["services"]
    observed["metrics"].update(
        on_time=sum(v["on_time"] for v in observed["visits"]),
        completed_services=sum(
            c["on_time"] == c["total"] and c["total"] > 0 for c in services
        ),
        missed_services=sum(c["on_time"] < c["total"] for c in services),
        rehandles=sum(j["kind"] == "rehandle" for j in completed),
        travel=sum(
            (
                sum(
                    p["end"] - p["start"]
                    for p in j.get("movement_stages", [])
                    if p.get("route")
                )
                if s.get("movement")
                else j.get("travel_minutes", 1)
            )
            for j in completed
        ),
        resource_wait_task_minutes=resource_wait,
        changes=candidate["metrics"]["changes"],
        completed_moves=len(completed),
        prediction_error=sum(c["on_time"] for c in candidate["services"])
        - sum(v["on_time"] for v in observed["visits"]),
    )
    result.update(
        execution_status=s["schedule"]["status"],
        observed=observed["metrics"],
        visits=observed["visits"],
        services=services,
        events=events,
        jobs=[
            dict(
                id=j["id"],
                container_id=j["container_id"],
                status=j["status"],
                started_at=j["started_at"],
                completed_at=j["completed_at"],
                resources=j["resources"],
            )
            for j in s["jobs"]
        ],
        interrupt_reason=s["schedule"].get("reason"),
        elapsed_seconds=round(time.monotonic() - started, 3),
    )
    return result


def evaluate_case(
    snapshot, spec, seeds, horizon=180, seconds=2, comparison=None, heartbeat=None
):
    started = time.monotonic()
    original = digest(snapshot)
    comparison = comparison or build(snapshot, horizon, seconds)
    if comparison["base_revision"] != snapshot["revision"]:
        raise RuleError("Evaluation comparison has a different state basis")
    trials = []
    baseline = next(
        (c for c in comparison["candidates"] if c["key"] == "baseline"), None
    )
    baseline_rows = {r["job_id"]: r for r in baseline["rows"]} if baseline else {}
    for seed in seeds:
        for candidate in comparison["candidates"]:
            if heartbeat:
                heartbeat()
            trial = simulate_candidate(
                snapshot, candidate, spec, seed, comparison["end_minute"]
            )
            trial["changed_bookings_vs_baseline"] = sum(
                r["job_id"] not in baseline_rows
                or (r["start"], r["resources"])
                != (
                    baseline_rows[r["job_id"]]["start"],
                    baseline_rows[r["job_id"]]["resources"],
                )
                for r in candidate["rows"]
            ) + len(set(baseline_rows) - {r["job_id"] for r in candidate["rows"]})
            trials.append(trial)
    assert digest(snapshot) == original, "Evaluation mutated the source snapshot"
    return dict(
        scenario=spec,
        snapshot_digest=original,
        comparison=comparison,
        trials=trials,
        elapsed_seconds=round(time.monotonic() - started, 3),
    )
