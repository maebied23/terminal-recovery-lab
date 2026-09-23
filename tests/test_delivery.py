"""Delivery contract and failure safety against a real disposable PostgreSQL database."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from app import api
from app.domain import by_id
from app.integration import receive, status
from app.evaluation import manifest, scenario_state
from app.stage_planning import dispatch_conflict
from app.store import Store
from test_datasets import db


def envelope():
    return dict(
        source="fleet",
        event_id="external-1",
        external_id="crane-west-1",
        kind="equipment.status",
        observed_at="2026-09-20T08:00:00Z",
        sequence=1,
        value="failed",
    )


def test_concurrent_delivery_restart_and_conflict(db):
    store, create = db
    run = create("baseline-shift")
    before = store.history(run, 0)["state"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: receive(store, run, envelope()), range(2)))
    assert sorted(r["status"] for r in results) == ["applied", "duplicate"]
    restarted = Store(store.dsn)
    assert by_id(restarted.read(run)["equipment"], "YC-1")["status"] == "failed"
    assert restarted.history(run, 0)["state"] == before
    conflict = dict(envelope(), value="available")
    assert receive(restarted, run, conflict)["status"] == "quarantined"
    assert (
        receive(restarted, run, dict(envelope(), event_id="stale", sequence=0))[
            "status"
        ]
        == "stale"
    )
    assert (
        receive(
            restarted, run, dict(envelope(), event_id="unknown", external_id="unknown")
        )["status"]
        == "quarantined"
    )
    assert (
        receive(
            restarted,
            run,
            dict(envelope(), event_id="future", observed_at="2026-09-20T08:10:00Z"),
        )["status"]
        == "quarantined"
    )
    assert status(store, run)["applied"] == 1
    assert by_id(store.read(run)["equipment"], "YC-1")["status"] == "failed"


def test_transaction_rollback_then_redelivery(db, monkeypatch):
    store, create = db
    run = create("baseline-shift")
    original = store.persist

    def crash(*args):
        original(*args)
        raise RuntimeError("injected failure before commit")

    monkeypatch.setattr(store, "persist", crash)
    with pytest.raises(RuntimeError):
        receive(store, run, envelope())
    assert store.read(run)["revision"] == 0 and status(store, run)["received"] == 0
    monkeypatch.setattr(store, "persist", original)
    assert receive(store, run, envelope())["status"] == "applied"


def test_adapter_scope_validation_csrf_and_limits(db, monkeypatch):
    store, create = db
    run = create("baseline-shift")
    monkeypatch.setattr(api, "store", store)
    monkeypatch.setenv("TERMINAL_FEED_TOKEN", "t" * 32)
    monkeypatch.setenv("TERMINAL_FEED_RUN", run)
    with TestClient(api.app) as c:
        payload = dict(envelope(), schema_version=1)
        url = "/api/integrations/equipment?run=" + run
        assert c.post(url, json=payload).status_code == 401
        headers = {"Authorization": "Bearer " + "t" * 32}
        assert c.post(url, json=payload, headers=headers).json()["status"] == "applied"
        assert (
            c.post(
                url, json=dict(payload, source="inventory"), headers=headers
            ).status_code
            == 403
        )
        assert (
            c.post(url, json=dict(payload, sequence=True), headers=headers).status_code
            == 422
        )
        assert (
            c.post("/api/commands?run=" + run, json={}, headers=headers).status_code
            == 403
        )
        assert c.post(url, content=b"x" * 65537, headers=headers).status_code == 413
        assert c.get("/api/live").status_code == 200
        monkeypatch.setenv("TERMINAL_ALLOWED_HOSTS", "review.example")
        assert (
            c.get("/api/state", headers={"host": "review.example"}).status_code == 403
        )
        monkeypatch.setenv("TERMINAL_PROXY_KEY", "p" * 32)
        assert (
            c.get("/api/state", headers={"host": "review.example"}).status_code == 403
        )
        assert (
            c.get(
                "/api/live",
                headers={"host": "review.example", "x-terminal-proxy": "p" * 32},
            ).status_code
            == 200
        )


def test_provenance_covers_movement_and_all_scenario_states():
    m = manifest()
    assert "app/move_execution.py" in m["source_hashes"]
    assert "sql/placement_temporal.sql" in m["source_hashes"]
    assert "requirements.lock.txt" in m["source_hashes"]
    assert len(m["movement"]) == 8
    for spec in m["movement"]:
        s = scenario_state(spec)
        assert s.get("movement") and "events" not in s


def test_dispatch_guard_is_distinct_from_later_stage_overlap():
    row = dict(start=4, resources=["YC-1", "TT-1"])
    previous = dict(
        resources=["YC-1"], stages=[dict(start=2, end=6, resources=["YC-1"])]
    )
    assert dispatch_conflict(row, previous)
    row["start"] = 6
    assert not dispatch_conflict(row, previous)


def test_observation_interrupts_booked_work_without_advancing_clock(db):
    store, create = db
    run = create("baseline-shift")
    with store.connect() as c:
        state = store.read(run, c, lock=True)
        state["schedule"] = dict(id="test-active-plan", status="approved", rows=[])
        state["revision"] += 1
        store.persist(c, run, state, [], None)
    before = store.read(run)
    receive(store, run, envelope())
    after = Store(store.dsn).read(run)
    assert after["schedule"]["status"] == "interrupted"
    assert after["minute"] == before["minute"]
    assert after["containers"] == before["containers"]
    assert not after["running"]


def test_applied_receipt_marks_active_bookings_as_exposure(db):
    store, create = db
    run = create("movement-shift")
    # The assigned future receiver is relevant before it acquires physical cargo.
    with store.connect() as c:
        state = store.read(run, c, lock=True)
        j = by_id(state["jobs"], "MV-001")
        j["assigned_resources"] = ["YC-3", "TT-1"]
        # Read projection query must follow the assigned resources of in-flight work.
        c.execute(
            "UPDATE move_jobs SET status='running',attributes=attributes || %s::jsonb WHERE run_id=%s AND id='MV-001'",
            ('{"assigned_resources":["YC-3","TT-1"]}', run),
        )
        from app.store import ROOT

        rows = c.execute(
            (ROOT / "sql/input_impact.sql").read_text(), {"run": run, "entity": "TT-1"}
        ).fetchall()
        assert any(r["commitment_id"] == "NORTH-RAIL" for r in rows)
