from copy import deepcopy
import pytest
from psycopg.types.json import Jsonb
from app.evaluation import (
    manifest,
    scenario_state,
    evaluate_case,
    simulate_candidate,
    digest,
)
from app.evaluation_store import enqueue, work, report, cancel
from app.scheduling import build
from app.domain import RuleError
from test_v1_store import db


@pytest.fixture(scope="module")
def basis():
    spec = manifest()["development"][0]
    s = scenario_state(spec)
    return s, spec, build(s, seconds=0.2)


def test_paired_streams_and_immutable_information_boundary(basis):
    s, spec, comparison = basis
    before = deepcopy(s)
    r = evaluate_case(s, spec, [101], comparison=comparison)
    streams = {
        t["duration_stream_digest"] for t in r["trials"] if t["validation"] == "passed"
    }
    assert len(streams) == 1
    assert s == before and r["snapshot_digest"] == digest(s)
    for t in r["trials"]:
        if t["observed"]:
            assert t["observed"]["on_time"] == sum(v["on_time"] for v in t["visits"])
            assert len(t["visits"]) == len({v["visit_id"] for v in t["visits"]})
            assert (
                t["observed"]["prediction_error"]
                == sum(v["on_time"] for v in t["predicted_services"])
                - t["observed"]["on_time"]
            )


def test_future_disruption_interrupts_without_changing_prediction(basis):
    s, _, comparison = basis
    c = next(c for c in comparison["candidates"] if c["key"] == "deadline")
    spec = dict(
        duration_factor=1,
        events=[
            dict(
                kind="equipment.status",
                entity_id="YC-3",
                value="failed",
                observed_minute=2,
                delivery_minute=2,
            )
        ],
    )
    t = simulate_candidate(s, c, spec, 101, 180)
    assert t["execution_status"] == "interrupted"
    assert t["predicted"] == c["metrics"]
    assert any(e["kind"] == "input.applied" for e in t["events"])
    assert not any(
        j["started_at"] and j["started_at"] >= 2
        for j in t["jobs"]
        if j["status"] != "queued"
    )


def test_longer_actual_handling_is_not_used_to_replan(basis):
    s, _, comparison = basis
    c = next(c for c in comparison["candidates"] if c["key"] == "deadline")
    t = simulate_candidate(s, c, dict(duration_factor=3, events=[]), 101, 180)
    assert t["execution_status"] == "interrupted"
    assert t["observed"]["on_time"] < sum(v["on_time"] for v in c["services"])


def test_all_scenario_initial_states_are_valid():
    m = manifest()
    for spec in m["development"] + m["holdout"]:
        s = scenario_state(spec)
        assert "events" not in s


def test_durable_sql_pairs_and_preserves_live_state(db, monkeypatch, basis):
    store, run = db
    before = store.read(run)
    s, spec, comparison = basis
    monkeypatch.setattr("app.evaluation_store.scenario_state", lambda _: deepcopy(s))
    original = manifest()
    original.update(development=[spec], seeds=[101], solver_seconds=0.2)
    monkeypatch.setattr("app.evaluation_store.manifest", lambda: deepcopy(original))
    eid = enqueue(store, run, 0, "development")
    assert work(store)
    r = report(store, run, eid, True)
    assert r["status"] == "completed", r
    assert len(r["trials"]) == 3 and len(r["cases"]) == 1
    assert all(
        x["attempted"] == 1 and x["paired"] == x["executed"] for x in r["summary"]
    )
    assert next(x for x in r["summary"] if x["strategy"] == "baseline")["paired"] == 1
    assert sum(x["samples"] for x in r["service_impact"]) == 5 * sum(
        x["executed"] for x in r["summary"]
    )
    assert store.read(run) == before
    with pytest.raises(RuleError):
        report(store, "different-run", eid)


def test_cancel_and_revision_checks(db):
    store, run = db
    with pytest.raises(RuleError):
        enqueue(store, run, 99, "case")
    eid = enqueue(store, run, 0, "case")
    with pytest.raises(RuleError):
        enqueue(store, run, 0, "case")
    with pytest.raises(RuleError):
        cancel(store, "wrong-run", eid)
    cancel(store, run, eid)
    assert not work(store)
    r = report(store, run, eid)
    assert not r["complete"] and not r["trials"]
    with pytest.raises(RuleError):
        enqueue(store, run, 0, "case", "not-a-plan")


def test_failed_candidate_is_in_coverage_not_paired_mean(db):
    store, run = db
    eid = enqueue(store, run, 0, "case")
    with store.connect() as c:
        for strategy, metrics, validation in [
            ("baseline", {"on_time": 4}, "passed"),
            ("deadline", {"on_time": 3}, "passed"),
            ("constraint", None, "failed"),
        ]:
            c.execute(
                "INSERT INTO evaluation_trials(evaluation_id,case_id,seed,strategy,validation,execution_status,metrics,details) VALUES(%s,%s,101,%s,%s,%s,%s,%s)",
                (
                    eid,
                    "selected-case",
                    strategy,
                    validation,
                    "completed" if metrics else "not_executable",
                    Jsonb(metrics) if metrics else None,
                    Jsonb({}),
                ),
            )
    r = {x["strategy"]: x for x in report(store, run, eid)["summary"]}
    assert r["deadline"]["losses"] == 1 and r["deadline"]["mean_delta"] == -1
    assert (
        r["constraint"]["attempted"] == 1
        and r["constraint"]["paired"] == 0
        and r["constraint"]["not_executable"] == 1
    )
    cancel(store, run, eid)


def test_cancelled_worker_cannot_commit_results(db, monkeypatch):
    store, run = db
    eid = enqueue(store, run, 0, "case")

    def cancelled(*args):
        cancel(store, run, eid)
        args[-1]()  # heartbeat must detect lost ownership
        raise AssertionError("Unreachable after cancellation")

    monkeypatch.setattr("app.evaluation_store.evaluate_case", cancelled)
    assert work(store)
    r = report(store, run, eid)
    assert r["status"] == "cancelled" and r["trials"] == []


def test_expired_case_reclaims_with_fenced_attempt(db, monkeypatch):
    store, run = db
    eid = enqueue(store, run, 0, "case")
    with store.connect() as c:
        c.execute(
            "UPDATE evaluation_cases SET status='running',attempts=3,lease_until=now()-interval '1 second' WHERE evaluation_id=%s",
            (eid,),
        )
    assert work(store)
    r = report(store, run, eid)
    assert r["status"] == "failed" and not r["complete"] and not r["trials"]
