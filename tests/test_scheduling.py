from copy import deepcopy
import uuid
import pytest
import psycopg
from psycopg.types.range import Range
from app.datasets import load_pack
from app.domain import by_id, transition, RuleError, validate
from app.scheduling import build, replay, greedy, constraint_schedule, windows
from app.schedule_store import enqueue, work, listing, feedback
from test_v1_store import db


@pytest.fixture(scope="module")
def comparison():
    s = load_pack("baseline-shift")["state"]
    return s, build(s, seconds=4)


def plan(s, r, key="deadline"):
    c = next(c for c in r["candidates"] if c["key"] == key)
    return dict(
        id="test-plan",
        base_revision=s["revision"],
        rows=c["rows"],
        end_minute=r["end_minute"],
        title=c["title"],
        projection=c["services"],
    )


def test_candidates_are_independently_validated_and_hold_not_solved(comparison):
    s, r = comparison
    assert r["base_revision"] == 0 and r["recommended"]
    for c in r["candidates"]:
        if c["validation"] == "passed":
            replay(s, c["rows"], r["end_minute"])
            assert all(x["container_id"] != "CT-0125" for x in c["rows"])
            assert sum(x["total"] for x in c["services"]) == 24
            assert len(c["visits"]) == len({x["visit_id"] for x in c["visits"]})
            assert c["metrics"]["missed"] >= 1
    assert (
        next(c for c in r["candidates"] if c["key"] == "baseline")["metrics"]["changes"]
        == 0
    )


def test_replay_rejects_bad_time_resources_and_overlapping_booking(comparison):
    s, r = comparison
    rows = deepcopy(plan(s, r)["rows"])
    rows[0]["start"] += 1
    with pytest.raises(RuleError):
        replay(s, rows, 180)
    rows = deepcopy(plan(s, r)["rows"])
    rows[0]["resources"] = ["QC-1"]
    with pytest.raises(RuleError):
        replay(s, rows, 180)
    rows = deepcopy(plan(s, r)["rows"])
    rows.append(deepcopy(rows[0]))
    with pytest.raises(RuleError, match="Duplicate"):
        replay(s, rows, 180)


def test_calendar_checks_whole_interval():
    s = load_pack("baseline-shift")["state"]
    s["availability"] = [dict(equipment_id="YC-1", start_minute=2, end_minute=5)]
    assert windows(s, ["YC-1"], 2, 2, 3) == [(2, 2)]
    assert windows(s, ["YC-1"], 3, 3, 3) == []


def test_timeout_keeps_honest_unknown():
    s = load_pack("normal-shift")["state"]
    rows, solver = constraint_schedule(s, 180, seconds=0)
    assert rows is None and solver["status"] == "UNKNOWN"


def test_approval_does_not_move_then_executes_exact_bookings(comparison):
    s, r = comparison
    p = plan(s, r)
    ns, events = transition(s, dict(action="approve_schedule", schedule_plan=p))
    assert ns["containers"] == s["containers"]
    assert ns["schedule"]["status"] == "approved"
    assert events[0]["kind"] == "schedule.approved"
    first = min(x["start"] for x in p["rows"])
    while ns["minute"] < first:
        ns, events = transition(ns, dict(action="advance", minutes=1))
    assert any(
        e["kind"] == "move.dispatched" and e["plan_id"] == "test-plan" for e in events
    )
    for _ in range(200):
        if ns["schedule"]["status"] in ("completed", "interrupted"):
            break
        ns, _ = transition(ns, dict(action="advance", minutes=1))
    assert ns["schedule"]["status"] == "completed", ns["schedule"].get("reason")
    assert not ns["running"]
    for row in p["rows"]:
        job = by_id(ns["jobs"], row["job_id"])
        assert job["started_at"] == row["start"] and job["completed_at"] <= row["end"]
    assert by_id(ns["jobs"], "MV-005")["status"] == "queued"


def test_failure_invalidates_future_but_preserves_inflight(comparison):
    s, r = comparison
    ns, _ = transition(s, dict(action="approve_schedule", schedule_plan=plan(s, r)))
    ns, _ = transition(ns, dict(action="advance", minutes=1))
    job = next(j for j in ns["jobs"] if j["status"] == "running")
    ns, events = transition(ns, dict(action="fail", entity_id=job["resources"][0]))
    assert ns["schedule"]["status"] == "interrupted"
    assert any(e["kind"] == "schedule.interrupted" for e in events)
    assert by_id(ns["jobs"], job["id"])["status"] == "running"
    before = sum(j["status"] == "queued" for j in ns["jobs"])
    ns, _ = transition(ns, dict(action="advance", minutes=5))
    assert sum(j["status"] == "queued" for j in ns["jobs"]) == before
    with pytest.raises(RuleError, match="paused"):
        build(ns, seconds=0)


def test_future_feed_is_not_planner_knowledge(comparison):
    s, r = comparison
    # Pack future events are stored outside the state snapshot; the planner only
    # accepts this explicit snapshot, never the run id or a database connection.
    other = load_pack("equipment-outage")["state"]
    assert s["equipment"] == other["equipment"]
    assert greedy(s, 180) == greedy(other, 180)


def test_impossible_cutoff_and_no_invented_position_repair():
    s = load_pack("impossible-cutoff")["state"]
    r = build(s, seconds=0.25)
    for c in r["candidates"]:
        if c["validation"] == "passed":
            assert (
                next(x for x in c["services"] if x["id"] == "NORTH-RAIL")["on_time"]
                == 0
            )
    s = load_pack("baseline-shift")["state"]
    by_id(s["containers"], "CT-0122")["location_id"] = "A2"
    by_id(s["containers"], "CT-0122")["tier"] = 5
    rows = greedy(s, 180)
    assert not any(x["job_id"] in ("MV-013", "MV-001", "MV-002") for x in rows)


@pytest.fixture
def schedule_db(db):
    yield db
    store, run = db
    with store.connect() as c:
        c.execute("DELETE FROM schedule_requests WHERE run_id=%s", (run,))


def test_durable_request_approval_idempotency_feedback_and_db_exclusion(schedule_db):
    store, run = schedule_db
    request = enqueue(store, run, 0, "NORTH-RAIL", 180)
    with pytest.raises(RuleError, match="already"):
        enqueue(store, run, 0, "NORTH-RAIL")
    assert work(store)
    saved = listing(store, run)[0]
    assert saved["id"] == request and saved["status"] == "completed", saved
    candidate = next(c for c in saved["result"]["candidates"] if c["key"] == "deadline")
    cmd = dict(
        action="approve_schedule",
        plan_id=candidate["plan_id"],
        command_id=str(uuid.uuid4()),
        expected_revision=0,
    )
    assert store.enqueue(run, cmd, "operator")["status"] == "queued"
    assert store.process_one()
    state = store.read(run)
    assert state["schedule"]["status"] == "approved"
    assert store.enqueue(run, cmd, "operator")["status"] == "acknowledged"
    assert len(feedback(store, run)) == len(candidate["rows"])
    with store.connect() as c:
        bookings = c.execute(
            "SELECT * FROM equipment_reservations WHERE run_id=%s", (run,)
        ).fetchall()
        assert bookings and all(b["active"] for b in bookings)
    # Shift one existing reservation onto another on the same equipment. SQL is
    # the last line of defense even if a caller bypasses Python validation.
    a, b = next(
        (a, b)
        for a in bookings
        for b in bookings
        if a["equipment_id"] == b["equipment_id"] and a["job_id"] != b["job_id"]
    )
    with pytest.raises(psycopg.errors.ExclusionViolation):
        with store.connect() as c:
            c.execute(
                "UPDATE equipment_reservations SET occupied=%s WHERE plan_id=%s AND job_id=%s AND equipment_id=%s",
                (a["occupied"], b["plan_id"], b["job_id"], b["equipment_id"]),
            )
    stale = dict(cmd, command_id=str(uuid.uuid4()), expected_revision=1)
    assert store.enqueue(run, stale, "operator")["status"] == "rejected"
    # Preserve earlier snapshot: approval changes booking state, not past facts.
    assert "schedule" not in store.history(run, 0)["state"]
    # Explicit withdrawal releases future work; approved evidence remains queryable.
    withdraw = dict(
        action="withdraw_schedule", expected_revision=1, command_id=str(uuid.uuid4())
    )
    store.enqueue(run, withdraw, "operator")
    store.process_one()
    with store.connect() as c:
        assert not c.execute(
            "SELECT 1 FROM equipment_reservations WHERE run_id=%s AND active", (run,)
        ).fetchone()
        # Fixture cleanup removes commands first: remove this slice's dependent history.
        c.execute("DELETE FROM schedule_requests WHERE run_id=%s", (run,))


def test_current_approved_schedule_is_baseline_and_running_moves_frozen(comparison):
    s, r = comparison
    ns, _ = transition(s, dict(action="approve_schedule", schedule_plan=plan(s, r)))
    ns, _ = transition(ns, dict(action="advance", minutes=1))
    again = build(ns, seconds=0)
    baseline = next(c for c in again["candidates"] if c["key"] == "baseline")
    assert baseline["title"] == "Keep approved bookings"
    assert baseline["validation"] == "passed"
    original = {x["job_id"]: x for x in plan(s, r)["rows"]}
    for row in baseline["rows"]:
        j = by_id(ns["jobs"], row["job_id"])
        if j["status"] == "running":
            assert row["frozen"] and row["resources"] == j["resources"]
            assert row["start"] == ns["minute"]
        else:
            assert row == original[row["job_id"]]


def test_late_input_interrupts_before_dispatch_and_batch_stops(comparison):
    s, r = comparison
    ns, _ = transition(s, dict(action="approve_schedule", schedule_plan=plan(s, r)))
    ns, events = transition(
        ns,
        dict(action="advance", minutes=15),
        before_tick=lambda _: [dict(kind="input.applied", entity_id="CT-0122")],
    )
    assert ns["minute"] == 1 and ns["schedule"]["status"] == "interrupted"
    assert not any(j["status"] == "running" for j in ns["jobs"])


def test_queued_approval_rechecks_revision_transactionally(schedule_db):
    store, run = schedule_db
    enqueue(store, run, 0, "NORTH-RAIL")
    work(store)
    p = next(
        c
        for c in listing(store, run)[0]["result"]["candidates"]
        if c["key"] == "deadline"
    )
    cmd = dict(
        action="approve_schedule",
        plan_id=p["plan_id"],
        command_id=str(uuid.uuid4()),
        expected_revision=0,
    )
    store.enqueue(run, cmd, "operator")
    with store.connect() as c:
        s = store.read(run, c, lock=True)
        ns, events = transition(s, dict(action="pause"))
        store.persist(c, run, ns, events, None)
    store.process_one()
    assert "schedule" not in store.read(run)
    with store.connect() as c:
        assert (
            c.execute(
                "SELECT status FROM commands WHERE id=%s", (cmd["command_id"],)
            ).fetchone()["status"]
            == "rejected"
        )
        assert not c.execute(
            "SELECT 1 FROM equipment_reservations WHERE run_id=%s", (run,)
        ).fetchone()
        assert (
            c.execute(
                "SELECT status FROM schedule_plans WHERE id=%s", (p["plan_id"],)
            ).fetchone()["status"]
            == "proposed"
        )


def test_approval_replay_rejects_corrupted_plan_and_rolls_back_bookings(schedule_db):
    from psycopg.types.json import Jsonb

    store, run = schedule_db
    enqueue(store, run, 0, "NORTH-RAIL")
    work(store)
    p = next(
        c
        for c in listing(store, run)[0]["result"]["candidates"]
        if c["key"] == "deadline"
    )
    altered = deepcopy(p)
    altered["rows"][0]["source_id"] = "GATE-IN"
    with store.connect() as c:
        c.execute(
            "UPDATE schedule_plans SET candidate=%s WHERE id=%s",
            (Jsonb(altered), p["plan_id"]),
        )
    cmd = dict(
        action="approve_schedule",
        plan_id=p["plan_id"],
        expected_revision=0,
        command_id=str(uuid.uuid4()),
    )
    store.enqueue(run, cmd, "operator")
    store.process_one()
    with store.connect() as c:
        assert (
            c.execute(
                "SELECT status FROM commands WHERE id=%s", (cmd["command_id"],)
            ).fetchone()["status"]
            == "rejected"
        )
        assert not c.execute(
            "SELECT 1 FROM equipment_reservations WHERE run_id=%s", (run,)
        ).fetchone()
        assert (
            c.execute(
                "SELECT status FROM schedule_plans WHERE id=%s", (p["plan_id"],)
            ).fetchone()["status"]
            == "proposed"
        )
    assert store.read(run)["revision"] == 0


def test_partial_lexicographic_optimum_does_not_claim_full_optimality():
    from app.scheduling import solver_status

    first_priority = [dict(status="OPTIMAL")]
    assert solver_status(first_priority, True, 5) == "FEASIBLE"
    assert (
        solver_status(first_priority + [dict(status="UNKNOWN")], True, 5) == "FEASIBLE"
    )
    assert solver_status(first_priority * 5, True, 5) == "OPTIMAL"
    assert solver_status([], False, 5) == "UNKNOWN"


def test_initialize_does_not_replay_applied_migrations(db, tmp_path, monkeypatch):
    from app import store as store_module

    store, run = db
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "001_already_applied.sql").write_text("SELECT 1 / 0;")
    monkeypatch.setattr(store_module, "ROOT", tmp_path)
    # Version 1 already exists in the actual database. Its SQL must never run again.
    store.initialize()
    assert store.read(run)["revision"] == 0
