"""Integration tests use isolated runs in the dedicated lab database only."""

import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from psycopg.types.json import Jsonb
from app.store import Store
from app.domain import seed_state, RuleError, by_id
from app.planning import enqueue_experiment, work_experiment


@pytest.fixture
def db():
    store = Store()
    store.initialize()
    run = "test-" + str(uuid.uuid4())[:8]
    with store.connect() as c:
        store.create_run(c, run, "Automated integration test", seed_state("small"))
    yield store, run
    with store.connect() as c:
        for table in ["outbox"]:
            c.execute(
                f"DELETE FROM {table} WHERE command_id IN (SELECT id FROM commands WHERE run_id=%s)",
                (run,),
            )
        for table in [
            "cargo_custody",
            "stage_reservations",
            "schedule_requests",
            "transport_edges",
            "transport_nodes",
            "plans",
            "experiments",
            "commands",
            "events",
            "snapshots",
            "observations",
            "job_dependencies",
            "move_jobs",
            "containers",
            "commitments",
            "equipment",
            "locations",
            "runs",
        ]:
            c.execute(
                f"DELETE FROM {table} WHERE "
                + ("id" if table == "runs" else "run_id")
                + "=%s",
                (run,),
            )


def cmd(action="fail", revision=0, **kwargs):
    return dict(
        action=action,
        entity_id="YC-1",
        command_id=str(uuid.uuid4()),
        expected_revision=revision,
        **kwargs,
    )


def drain(store):
    for _ in range(100):
        if not store.process_one():
            return
    raise AssertionError("Queue did not drain")


def test_roundtrip_relational_and_restart(db):
    store, run = db
    s = store.read(run)
    assert len(s["containers"]) == 24 and len(s["jobs"]) == 37
    request = cmd()
    store.enqueue(run, request, "scenario-admin")
    drain(store)
    assert Store().read(run)["revision"] == 1
    assert by_id(store.read(run)["equipment"], "YC-1")["status"] == "failed"
    assert store.history(run, 0)["state"]["revision"] == 0
    assert (
        by_id(store.history(run, 0)["state"]["equipment"], "YC-1")["status"]
        == "available"
    )


def test_duplicate_id_stale_and_rejection_are_durable(db):
    store, run = db
    request = cmd()
    store.enqueue(run, request, "scenario-admin")
    drain(store)
    assert store.enqueue(run, request, "scenario-admin")["status"] == "acknowledged"
    with pytest.raises(RuleError):
        store.enqueue(run, dict(request, action="repair"), "scenario-admin")
    result = store.enqueue(run, cmd(), "scenario-admin")
    assert result["status"] == "rejected"
    assert store.read(run)["revision"] == 1
    assert len(store.list_rows("commands", run)) == 2


def test_simultaneous_commands_cannot_overwrite(db):
    store, run = db
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: store.enqueue(run, cmd(), "scenario-admin"), range(2)))
    drain(store)
    statuses = [c["status"] for c in store.list_rows("commands", run)]
    assert sorted(statuses) == ["acknowledged", "rejected"]
    assert store.read(run)["revision"] == 1


def test_rule_rejection_rolls_back_state_but_records_delivery(db):
    store, run = db
    request = cmd("dispatch")
    request["entity_id"] = "MV-001"
    store.enqueue(run, request, "operator")
    drain(store)
    assert store.read(run)["revision"] == 0
    assert store.list_rows("commands", run)[0]["status"] == "rejected"
    assert len(store.list_rows("events", run)) == 0


def test_delivery_failure_rolls_back_before_bounded_retry(db, monkeypatch):
    store, run = db
    store.enqueue(run, cmd(), "scenario-admin")
    original = store.persist

    def broken(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("test crash before acknowledgement")

    monkeypatch.setattr(store, "persist", broken)
    store.process_one()
    assert store.read(run)["revision"] == 0
    assert not store.list_rows("events", run)
    monkeypatch.setattr(store, "persist", original)
    with store.connect() as c:
        c.execute(
            "UPDATE outbox SET available_at=now() WHERE command_id IN (SELECT id FROM commands WHERE run_id=%s)",
            (run,),
        )
    drain(store)
    assert store.read(run)["revision"] == 1
    assert len(store.list_rows("events", run)) == 1


def test_historical_correction_preserves_record_axis(db):
    store, run = db
    store.enqueue(run, cmd(), "scenario-admin")
    drain(store)
    store.enqueue(
        run, cmd("correct", 1, valid_minute=0, value="available"), "scenario-admin"
    )
    drain(store)
    assert (
        by_id(store.history(run, 1)["state"]["equipment"], "YC-1")["status"] == "failed"
    )
    assert by_id(store.read(run)["equipment"], "YC-1")["status"] == "available"
    assert len(store.read(run)["observations"]) == 2


def test_experiment_approval_and_stale_plan(db):
    store, run = db
    id = enqueue_experiment(store, run, seeds=2, horizon=60)
    assert work_experiment(store)
    row = next(e for e in store.list_rows("experiments", run) if e["id"] == id)
    assert row["status"] == "completed"
    assert len(row["result"]["candidates"]) == 4
    pid = row["result"]["candidates"][1]["plan_id"]
    request = cmd("approve_plan", plan_id=pid)
    store.enqueue(run, request, "operator")
    drain(store)
    assert store.read(run)["policy"] == "rail-first"
    assert (
        store.enqueue(run, cmd("approve_plan", 1, plan_id=pid), "operator")["status"]
        == "rejected"
    )


def test_access_jobs_and_dependency_reasons_survive_restart(db):
    from app.rehandles import propose
    from app.domain import transition

    store, run = db
    # Standard profile has inert inventory available to make an unplanned obstruction.
    with store.connect() as c:
        s = store.read(run, c, lock=True)
        replacement = seed_state("standard")
        replacement["revision"] = s["revision"] + 1
        store.persist(c, run, replacement, [], None)
    request = cmd("obstruct", 1)
    request["entity_id"] = "CT-0123"
    store.enqueue(run, request, "scenario-admin")
    drain(store)
    p = propose(store.read(run), "MV-003")
    request = cmd("approve_access", 2, proposal_token=p["token"])
    request["entity_id"] = "MV-003"
    store.enqueue(run, request, "operator")
    drain(store)
    s = Store().read(run)
    assert s["revision"] == 3
    assert by_id(s["jobs"], "MV-003")["dependency_details"]
    assert by_id(s["containers"], "CT-0123")["location_id"] == "A3"
    with store.connect() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM cargo_visits WHERE run_id=%s", (run,)
            ).fetchone()["n"]
            == 144
        )


def test_feed_rehearsal_dedupe_quarantine_and_no_state_mutation(db):
    from app.inputs import record

    store, run = db
    before = store.read(run)
    payload = dict(
        source="TOS-rehearsal",
        source_event_id="1",
        entity_id="YC-1",
        event_time=0,
        value="failed",
    )
    a = record(store, run, payload)
    assert a["status"] == "accepted"
    assert record(store, run, payload)["id"] == a["id"]
    with pytest.raises(RuleError):
        record(store, run, dict(payload, value="available"))
    assert (
        record(store, run, dict(payload, source_event_id="2", entity_id="UNKNOWN"))[
            "status"
        ]
        == "quarantined"
    )
    assert (
        record(store, run, dict(payload, source_event_id="3", event_time=999))["status"]
        == "quarantined"
    )
    assert store.read(run) == before


def test_pause_survives_stale_submission_and_execution(db):
    from app.domain import transition
    store,run=db
    with store.connect() as c:
        s=store.read(run,c,lock=True)
        s,_=transition(s,dict(action='clock',running=True,speed=5))
        store.persist(c,run,s,[],None)
    request=cmd('pause',0)
    assert store.enqueue(run,request,'operator')['status']=='queued'
    with store.connect() as c:
        s=store.read(run,c,lock=True)
        s,_=transition(s,dict(action='advance',minutes=1))
        store.persist(c,run,s,[],None)
    drain(store)
    s=store.read(run)
    assert not s['running'] and s['speed']==5 and s['minute']==1
    assert store.list_rows('commands',run)[0]['status']=='acknowledged'
