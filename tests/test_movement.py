"""Physical continuity, temporal capacity, typed persistence, and legacy isolation."""

from copy import deepcopy
import uuid
import pytest
from psycopg.types.json import Jsonb
from app.datasets import load_pack
from app.domain import by_id, transition, tick, validate, dispatch, RuleError
from app.movement import route, make_row, validate_network
from app.scheduling import greedy, replay, build
from app.schedule_execution import activate
from app.placement import rewrite
from app.placement_store import create
from app.store import ROOT
from test_v1_store import db, drain


def state():
    return load_pack("movement-shift")["state"]


def one_move():
    s = state()
    j = by_id(s["jobs"], "MV-013")
    s["jobs"] = [j]
    return s, j


def test_legacy_pack_unchanged_and_network_validation():
    assert "movement" not in load_pack("baseline-shift")["state"]
    s = state()
    net = deepcopy(s["movement"])
    net["edges"][0]["metres"] = 0
    with pytest.raises(RuleError):
        validate_network(net, s)
    net = deepcopy(s["movement"])
    net["initial_positions"].clear()
    with pytest.raises(RuleError):
        validate_network(net, s)


def test_routes_units_direction_closure_and_destination_cost():
    s = state()
    r = route(s, "A1", "D4")
    assert r["metres"] > 0 and r["minutes"] > 0
    changed, _ = rewrite(s, "MV-013", "A2")
    assert route(changed, "A1", "A2")["minutes"] != r["minutes"]
    edge = by_id(s["movement"]["edges"], r["edges"][0])
    edge["closed"] = True
    with pytest.raises(RuleError, match="No open"):
        route(s, "A1", "D4")
    assert route(s, "D4", "A1")["minutes"] > 0  # closure is directed


def test_empty_travel_custody_and_handler_release():
    s, j = one_move()
    ids = ["YC-1", "YC-2", "TT-1"]
    r = make_row(s, j, 0, ids)
    assert r["stages"][0]["kind"] == "empty"
    dispatch(s, j, ids)
    c = by_id(s["containers"], j["container_id"])
    assert c["location_id"] == "A1" and j["resources"] == ["TT-1"]
    observed = []
    while j["status"] != "completed":
        s, events = tick(s, dispatch_hook=lambda *_: None)
        j = s["jobs"][0]
        c = by_id(s["containers"], j["container_id"])
        observed.extend(e["kind"] for e in events)
        if j["movement_stages"][j["stage_index"]]["kind"] == "transfer":
            assert c["custody"] == dict(kind="equipment", id="TT-1")
            assert by_id(s["equipment"], "YC-1")["job_id"] is None
        validate(s)
    assert c["custody"] == dict(kind="location", id="D4")
    assert "move.handover" in observed and "move.completed" in observed
    assert j["completed_at"] == r["end"]


def test_receiver_failure_waits_without_losing_tractor_then_repair():
    s, j = one_move()
    dispatch(s, j, ["YC-1", "YC-2", "TT-1"])
    while j["movement_stages"][j["stage_index"]]["kind"] != "transfer":
        s, _ = tick(s, dispatch_hook=lambda *_: None)
        j = s["jobs"][0]
    by_id(s["equipment"], "YC-2")["status"] = "failed"
    for _ in range(15):
        s, _ = tick(s, dispatch_hook=lambda *_: None)
    j = s["jobs"][0]
    c = by_id(s["containers"], j["container_id"])
    assert j["status"] == "running" and j["waiting_reason"]
    assert c["custody"] == dict(kind="equipment", id="TT-1")
    assert by_id(s["equipment"], "TT-1")["job_id"] == j["id"]
    by_id(s["equipment"], "YC-2")["status"] = "available"
    for _ in range(5):
        s, _ = tick(s, dispatch_hook=lambda *_: None)
    assert s["jobs"][0]["status"] == "completed"


def test_stage_replay_and_position_forgery():
    s = state()
    rows = greedy(s, 80)
    assert len(rows) > 3
    replay(s, rows, 80)
    bad = deepcopy(rows)
    empty = next(p for r in bad for p in r["stages"] if p["kind"] == "empty")
    empty["route"]["source"] = "J9"
    with pytest.raises(RuleError):
        replay(s, bad, 80)


def test_route_closure_preserves_recorded_history_and_custody():
    s, j = one_move()
    dispatch(s, j, ["YC-1", "YC-2", "TT-1"])
    while j["movement_stages"][j["stage_index"]]["kind"] != "transfer":
        s, _ = tick(s, dispatch_hook=lambda *_: None)
        j = s["jobs"][0]
    edge = j["movement_stages"][j["stage_index"]]["route"]["edges"][0]
    before = deepcopy(s)
    changed, _ = transition(s, dict(action="close_route", entity_id=edge))
    after, _ = tick(changed, dispatch_hook=lambda *_: None)
    assert after["jobs"][0]["stage_remaining"] == before["jobs"][0]["stage_remaining"]
    assert (
        s == before
        and by_id(after["containers"], j["container_id"])["custody"]["kind"]
        == "equipment"
    )


def test_actual_capacity_not_freed_by_expected_departure():
    s = state()
    target = by_id(s["locations"], "D4")
    target["capacity"] = sum(c["location_id"] == "D4" for c in s["containers"])
    # Tighten only to a valid nonempty current stack.
    assert target["capacity"] > 0
    assert not any(r["job_id"] == "MV-013" for r in greedy(s, 40))


def test_sql_projection_approval_and_history(db):
    store, run = db
    s = state()
    with store.connect() as c:
        store.persist(c, run, s, [], None)
    p = create(store, run, 0, "MV-013")
    assert any(
        x.get("occupancy") for x in p["candidates"] if x["validation"] == "passed"
    )
    with store.connect() as c:
        assert c.execute(
            "SELECT count(*) n FROM cargo_custody WHERE run_id=%s", (run,)
        ).fetchone()["n"] == len(s["containers"])
        assert (
            c.execute(
                "SELECT count(*) n FROM transport_edges WHERE run_id=%s", (run,)
            ).fetchone()["n"]
            > 0
        )
    # Existing old snapshot was written by db fixture and must not be overwritten.
    assert "movement" not in store.history(run, 0)["state"]


def test_stage_reservation_transaction_and_restart(db):
    from app.schedule_store import enqueue, work
    from app.store import Store

    store, run = db
    s = state()
    with store.connect() as c:
        store.persist(c, run, s, [], None)
    request = enqueue(store, run, 0, "NORTH-RAIL", 80)
    while work(store):
        pass
    with store.connect() as c:
        p = c.execute(
            "SELECT id FROM schedule_plans WHERE request_id=%s AND candidate->>'key'='deadline'",
            (request,),
        ).fetchone()
    assert p
    store.enqueue(
        run,
        dict(
            action="approve_schedule",
            plan_id=p["id"],
            command_id=str(uuid.uuid4()),
            expected_revision=0,
        ),
        "operator",
    )
    drain(store)
    current = Store().read(run)
    assert current["schedule"]["status"] == "approved"
    with store.connect() as c:
        assert (
            c.execute(
                "SELECT count(*) n FROM stage_reservations WHERE run_id=%s AND active",
                (run,),
            ).fetchone()["n"]
            > 0
        )
        assert (
            c.execute(
                "SELECT count(*) n FROM equipment_reservations WHERE run_id=%s AND active",
                (run,),
            ).fetchone()["n"]
            == 0
        )
    store.enqueue(
        run,
        dict(
            action="advance",
            minutes=8,
            command_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
        ),
        "operator",
    )
    drain(store)
    current = Store().read(run)
    validate(current)
    assert current["minute"] == 8
    store.enqueue(
        run,
        dict(
            action="fail",
            entity_id="YC-2",
            command_id=str(uuid.uuid4()),
            expected_revision=current["revision"],
        ),
        "scenario-admin",
    )
    drain(store)
    current = Store().read(run)
    assert current["schedule"]["status"] == "interrupted"
    validate(current)
    with store.connect() as c:
        booked = c.execute(
            "SELECT job_id,equipment_id FROM stage_reservations WHERE run_id=%s AND active",
            (run,),
        ).fetchall()
    assert all(
        by_id(current["jobs"], r["job_id"])["status"] == "running"
        and r["equipment_id"] in by_id(current["jobs"], r["job_id"])["resources"]
        for r in booked
    )


def test_observed_stage_activity_does_not_disappear_after_release():
    s, j = one_move()
    dispatch(s, j, ["YC-1", "YC-2", "TT-1"])
    while s["jobs"][0]["status"] != "completed":
        s, _ = tick(s, dispatch_hook=lambda *_: None)
    j = s["jobs"][0]
    assert j["resources"] == []
    assert all(p["end"] is not None for p in j["stage_history"])
    assert any("YC-1" in p["resources"] for p in j["stage_history"])
    assert any("YC-2" in p["resources"] for p in j["stage_history"])


def test_same_equipment_stage_use_cannot_overlap():
    s, j = one_move()
    r = make_row(s, j, 1, ["YC-3", "TT-1"])
    from app.movement import intervals

    crane = [(a, b) for e, a, b in intervals(r) if e == "YC-3"]
    assert len(crane) == 2 and crane[0][1] <= crane[1][0]


def test_closed_route_freezes_scheduled_execution_without_false_completion():
    s, j = one_move()
    rows = greedy(s, 40)
    plan = dict(
        id="test-plan",
        base_revision=0,
        end_minute=40,
        rows=rows,
        title="Test",
        projection=[],
    )
    activate(s, plan, [])
    for _ in range(2):
        s, _ = tick(s)
    current = s["jobs"][0]
    edge = current["movement_stages"][current["stage_index"]]["route"]["edges"][0]
    s, _ = transition(s, dict(action="close_route", entity_id=edge))
    assert s["schedule"]["status"] == "interrupted" and not s["running"]
    before = s["jobs"][0]["stage_remaining"]
    s, _ = tick(s)
    assert s["jobs"][0]["stage_remaining"] == before
    assert s["jobs"][0]["status"] == "running"


def test_failed_future_receiver_has_no_known_completion_for_replanning():
    s, j = one_move()
    dispatch(s, j, ["YC-1", "YC-2", "TT-1"])
    by_id(s["equipment"], "YC-2")["status"] = "failed"
    from app.movement import unknown_completion

    assert unknown_completion(s, j)
    with pytest.raises(RuleError, match="in-progress"):
        build(s, 40)
