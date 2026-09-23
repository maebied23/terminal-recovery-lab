from copy import deepcopy
import pytest
from app.domain import (
    seed_state,
    by_id,
    blockers,
    validate,
    RuleError,
    dispatch,
    enrich,
    transition,
)
from app.rehandles import propose


def obstruct():
    s = seed_state()
    # Give active pickup MV-003 a previously unplanned inert cover.
    c = next(
        c
        for c in s["containers"]
        if not c["commitment_id"] and c["location_id"] == "B1" and c["tier"] == 4
    )
    c.update(location_id="A3", tier=6)
    validate(s)
    return s


def test_future_yard_pickup_does_not_inspect_vessel_stack():
    s = seed_state()
    assert "Another container is stacked above" not in blockers(
        s, by_id(s["jobs"], "MV-015")
    )
    assert "Cargo not at planned pickup" in blockers(s, by_id(s["jobs"], "MV-015"))


def test_dag_and_foreign_relationship_validation():
    for deps in [["MV-001"], ["unknown"]]:
        s = seed_state()
        s["jobs"][0]["dependencies"] = deps
        with pytest.raises(RuleError):
            validate(s)
    s = seed_state()
    s["jobs"][12]["dependencies"] = ["MV-001"]
    with pytest.raises(RuleError, match="Circular"):
        validate(s)


def test_discharge_reserves_receiving_yard_resource():
    s = seed_state()
    j = by_id(s["jobs"], "MV-014")
    dispatch(s, j)
    assert {by_id(s["equipment"], r)["kind"] for r in j["resources"]} == {
        "quay",
        "yard",
        "tractor",
    }
    validate(s)


def test_access_proposal_approval_preserves_positions_and_rejects_stale():
    s = obstruct()
    before = deepcopy(s)
    p = propose(s, "MV-003")
    assert s == before
    ns, events = transition(
        s, dict(action="approve_access", entity_id="MV-003", proposal_token=p["token"])
    )
    assert ns["containers"] == s["containers"]
    assert len(ns["jobs"]) == len(s["jobs"]) + 1
    assert ns["jobs"][2]["dependencies"]
    assert events[0]["kind"] == "plan.access_approved"
    shifted = deepcopy(s)
    shifted["revision"] += 1
    with pytest.raises(RuleError, match="stale"):
        transition(
            shifted,
            dict(
                action="approve_access", entity_id="MV-003", proposal_token=p["token"]
            ),
        )
    with pytest.raises(RuleError, match="Existing"):
        propose(ns, "MV-003")


def test_no_destination_fails_without_mutation():
    s = obstruct()
    for l in s["locations"]:
        if l["kind"] == "yard":
            l["capacity"] = 1
    before = deepcopy(s)
    with pytest.raises(RuleError, match="No safe"):
        propose(s, "MV-003")
    assert s == before


def test_projection_covers_all_relationship_endpoints():
    s = enrich(seed_state())
    ids = {n["id"] for n in s["relationships"]["nodes"]}
    assert all(
        e["source"] in ids and e["target"] in ids for e in s["relationships"]["edges"]
    )
    assert by_id(s["jobs"], "MV-014")["container_id"] == "CT-0133"
    assert by_id(s["jobs"], "MV-015")["predecessors"][0]["kind"] == "sequence"


def test_observed_mode_rejects_simulator_completion():
    s = seed_state()
    s["data_mode"] = "observed"
    with pytest.raises(RuleError, match="cannot mutate"):
        transition(s, dict(action="advance"))


def test_cross_zone_rehandle_reserves_destination_handling():
    s = seed_state()
    j = by_id(s["jobs"], "MV-013")
    dispatch(s, j)
    yard = [
        by_id(s["equipment"], r)
        for r in j["resources"]
        if by_id(s["equipment"], r)["kind"] == "yard"
    ]
    assert len(yard) == 2
    assert any(e["zone"] in ("east", "all") for e in yard)


def test_shared_inspection_includes_arriving_cargo_on_vessel():
    from app.tools import inspect_entity

    r = inspect_entity(seed_state(), "AURORA")
    assert any(j["id"] == "MV-014" for j in r["jobs"])
    assert any(j["kind"] == "load" for j in r["jobs"])
    assert inspect_entity(seed_state(), "D1")["jobs"]


def test_multiple_covers_plan_in_top_first_order():
    s = obstruct()
    extra = next(
        c
        for c in s["containers"]
        if not c["commitment_id"] and c["location_id"] == "B2" and c["tier"] == 4
    )
    extra.update(location_id="A3", tier=7)
    validate(s)
    p = propose(s, "MV-003")
    assert len(p["moves"]) == 2 and p["moves"][0]["container_id"] == extra["id"]
    ns, _ = transition(
        s, dict(action="approve_access", entity_id="MV-003", proposal_token=p["token"])
    )
    added = ns["jobs"][-2:]
    assert added[1]["dependencies"] == [added[0]["id"]]
    assert by_id(ns["jobs"], "MV-003")["dependencies"] == [added[1]["id"]]


def test_command_event_occurs_now_unless_explicit_late_correction():
    s = seed_state()
    s["minute"] = 12
    ns, events = transition(s, dict(action="fail", entity_id="YC-1", valid_minute=0))
    assert events[-1]["valid_minute"] == 12
    _, events = transition(
        ns, dict(action="correct", entity_id="YC-1", valid_minute=2, value="available")
    )
    assert events[-1]["valid_minute"] == 2
