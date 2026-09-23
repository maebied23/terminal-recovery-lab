from copy import deepcopy
import pytest
from app.domain import (
    seed_state,
    transition,
    tick,
    by_id,
    blockers,
    dispatch,
    validate,
    RuleError,
    simulate,
    duration,
    apply_policy,
)


@pytest.mark.parametrize("profile", ["small", "standard"])
def test_seed_conservation_and_links(profile):
    s = seed_state(profile)
    validate(s)
    assert len(s["containers"]) == (24 if profile == "small" else 144)
    assert len(s["jobs"]) == 37
    for job in s["jobs"]:
        assert by_id(s["containers"], job["container_id"])
        for d in job["dependencies"]:
            assert by_id(s["jobs"], d)


def test_precedence_accessibility_authority_separate():
    s = seed_state()
    assert "Predecessor move incomplete" in blockers(s, by_id(s["jobs"], "MV-001"))
    assert "Another container is stacked above" in blockers(
        s, by_id(s["jobs"], "MV-001")
    )
    assert "Outbound authority hold" in blockers(s, by_id(s["jobs"], "MV-005"))
    with pytest.raises(RuleError):
        transition(s, dict(action="dispatch", entity_id="MV-001"))
    assert s == seed_state()


def test_inflight_failure_freezes_load_and_resources():
    s, _ = transition(seed_state(), dict(action="advance", minutes=1))
    j = next(
        j for j in s["jobs"] if j["status"] == "running" and j["equipment_id"] == "YC-1"
    )
    before = j["remaining"]
    cargo = j["container_id"]
    jid = j["id"]
    s, _ = transition(s, dict(action="fail", entity_id="YC-1"))
    s, _ = transition(s, dict(action="advance", minutes=6))
    apply_policy(s, "deadline")
    assert by_id(s["jobs"], jid)["remaining"] == before
    assert by_id(s["containers"], cargo)["location_id"] is None
    assert by_id(s["equipment"], "YC-1")["job_id"] == jid
    assert by_id(s["jobs"], jid)["equipment_id"] == "YC-1"
    s, _ = transition(s, dict(action="repair", entity_id="YC-1"))
    s, _ = transition(s, dict(action="advance", minutes=10))
    assert by_id(s["jobs"], jid)["status"] == "completed"


def test_destinations_reserve_capacity_before_completion():
    s = seed_state()
    by_id(s["locations"], "RAIL-1")["capacity"] = 1
    dispatch(s, by_id(s["jobs"], "MV-003"))
    assert "Destination capacity reserved/full" in blockers(
        s, by_id(s["jobs"], "MV-004")
    )
    validate(s)


def test_independent_resources_work_concurrently():
    s, _ = tick(seed_state())
    running = [j for j in s["jobs"] if j["status"] == "running"]
    assert len(running) >= 2
    resources = [r for j in running for r in j["resources"]]
    assert len(resources) == len(set(resources))


def test_duration_stream_independent_of_scheduler_order():
    jobs = seed_state()["jobs"]
    a = {j["id"]: duration(19, j) for j in jobs}
    b = {j["id"]: duration(19, j) for j in reversed(jobs)}
    assert a == b


def test_reproducible_complete_import_export():
    s = seed_state("small")
    apply_policy(s, "deadline")
    for c in s["containers"]:
        c["released"] = True
    for _ in range(180):
        s, _ = tick(s)
    for kind in ("receive", "load", "discharge", "retrieve", "rehandle"):
        assert any(j["kind"] == kind and j["status"] == "completed" for j in s["jobs"])
    assert any(
        c["flow"] == "export-vessel" and c["location_id"] in ("VESSEL-1", "VESSEL-2")
        for c in s["containers"]
    )
    assert any(
        c["flow"] == "import" and c["location_id"] == "TRUCK-OUT"
        for c in s["containers"]
    )
    assert simulate(seed_state("small"), "deadline", 42) == simulate(
        seed_state("small"), "deadline", 42
    )


def test_late_correction_preserves_newer_valid_observation():
    s, _ = transition(seed_state(), dict(action="advance", minutes=5))
    s, _ = transition(s, dict(action="fail", entity_id="YC-1"))
    old = deepcopy(s)
    s, _ = transition(
        s, dict(action="correct", entity_id="YC-1", valid_minute=2, value="available")
    )
    assert by_id(s["equipment"], "YC-1")["status"] == "failed"
    assert s["observations"][-1]["valid_minute"] == 2
    assert s["observations"][-1]["recorded_minute"] == 5
    assert old["observations"] != s["observations"]
    with pytest.raises(RuleError):
        transition(
            s,
            dict(
                action="correct", entity_id="YC-1", valid_minute=10, value="available"
            ),
        )


def test_batched_ticks_keep_occurrence_minutes():
    s, events = transition(seed_state(), dict(action="advance", minutes=10))
    assert any(e["valid_minute"] == 1 for e in events if e["kind"] == "move.dispatched")
    assert all(e["valid_minute"] <= s["minute"] for e in events)


def test_no_departure_with_inflight_load():
    s = seed_state()
    co = by_id(s["commitments"], "NORTH-RAIL")
    dispatch(s, by_id(s["jobs"], "MV-003"))
    co["cutoff"] = 1
    co["status"] = "open"
    s, _ = tick(s)
    s, _ = tick(s)
    assert by_id(s["commitments"], "NORTH-RAIL")["status"] == "closing"
    for _ in range(20):
        s, _ = tick(s)
    assert by_id(s["commitments"], "NORTH-RAIL")["status"] == "departed"


@pytest.mark.parametrize("policy", ["fifo", "rail-first", "deadline", "vessel-first"])
def test_policies_preserve_invariants_with_disruption(policy):
    s, _ = transition(seed_state("small"), dict(action="fail", entity_id="YC-1"))
    apply_policy(s, policy)
    for minute in range(180):
        if minute == 25:
            s, _ = transition(s, dict(action="repair", entity_id="YC-1"))
        s, _ = tick(s)
        validate(s)
