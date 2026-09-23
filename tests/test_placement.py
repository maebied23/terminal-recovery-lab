"""New destination decisions: SQL grain, bounded replay, atomic instructions, history."""

from copy import deepcopy
import uuid
import pytest
from app.domain import seed_state, by_id, RuleError, transition
from app.placement import rewrite, guard, apply
from app.datasets import load_pack
from app.placement_store import create
from app.store import ROOT
from test_v1_store import db, drain


def test_rewrite_changes_handoff_not_positions():
    s = seed_state()
    updated, changes = rewrite(s, "MV-013", "D3")
    assert by_id(updated["jobs"], "MV-013")["target_id"] == "D3"
    assert by_id(updated["jobs"], "MV-002")["source_id"] == "D3"
    assert updated["containers"] == s["containers"]
    assert updated["equipment"] == s["equipment"]
    assert by_id(s["jobs"], "MV-002")["source_id"] == "D4"
    assert {c["field"] for c in changes} >= {"source_id", "target_id"}


def test_ambiguous_or_running_handoff_rejected():
    s = seed_state()
    extra = deepcopy(by_id(s["jobs"], "MV-002"))
    extra["id"] = "AMBIGUOUS"
    s["jobs"].append(extra)
    with pytest.raises(RuleError, match="Ambiguous"):
        rewrite(s, "MV-013", "D3")
    s = seed_state()
    by_id(s["jobs"], "MV-002")["status"] = "running"
    with pytest.raises(RuleError):
        rewrite(s, "MV-013", "D3")


def test_booking_contract_and_external_mode_guard():
    s = seed_state()
    s["schedule"] = {"status": "withdrawn"}
    with pytest.raises(RuleError, match="automatic dispatch"):
        guard(s, "MV-013")
    s.pop("schedule")
    s["data_mode"] = "external"
    with pytest.raises(RuleError, match="synthetic"):
        guard(s, "MV-013")


def standard_fixture(store, run):
    with store.connect() as c:
        # Fresh isolated run from db fixture; replace initial small fixture before any action.
        s = load_pack("baseline-shift")["state"]
        store.persist(c, run, s, [], None)
    return s


def test_sql_grain_capacity_and_dependency_closure(db):
    store, run = db
    standard_fixture(store, run)
    with store.connect() as c:
        query = (ROOT / "sql/placement_candidates.sql").read_text()
        rows = c.execute(query, dict(run=run, job="MV-013")).fetchall()
        assert len(rows) == 23
        assert len({r["destination"] for r in rows}) == 23
        d4 = next(r for r in rows if r["destination"] == "D4")
        assert {"MV-013", "MV-001", "MV-002"} <= set(d4["affected_jobs"])
        assert "NORTH-RAIL" in d4["affected_departures"]
        assert all(
            r["free_slots"] == r["capacity"] - r["occupied"] - r["incoming"]
            for r in rows
        )
        assert c.execute(query, dict(run="other-run", job="MV-013")).fetchall() == []
        c.execute("UPDATE locations SET capacity=1 WHERE run_id=%s AND id='D4'", (run,))
        d4 = next(
            r
            for r in c.execute(query, dict(run=run, job="MV-013")).fetchall()
            if r["destination"] == "D4"
        )
        assert d4["excluded_reason"] == "No uncommitted capacity"


def test_compare_apply_history_and_stale(db):
    store, run = db
    initial = standard_fixture(store, run)
    result = create(store, run, 0, "MV-013")
    assert store.read(run)["revision"] == 0
    options = [
        c
        for c in result["candidates"]
        if c["validation"] == "passed" and not c["prescribed"]
    ]
    assert options, result
    choice = options[0]
    before = store.read(run)
    command_id = str(uuid.uuid4())
    store.enqueue(
        run,
        dict(
            command_id=command_id,
            expected_revision=0,
            action="approve_placement",
            plan_id=result["id"],
            destination_id=choice["destination"],
        ),
        "operator",
    )
    drain(store)
    after = store.read(run)
    with store.connect() as c:
        cmd = c.execute("SELECT * FROM commands WHERE id=%s", (command_id,)).fetchone()
        assert cmd["status"] == "acknowledged", cmd
        assert (
            c.execute(
                "SELECT count(*) AS n FROM equipment_reservations WHERE run_id=%s",
                (run,),
            ).fetchone()["n"]
            == 0
        )
        old = c.execute(
            "SELECT state FROM snapshots WHERE run_id=%s AND revision=0", (run,)
        ).fetchone()["state"]
        assert by_id(old["jobs"], "MV-013")["target_id"] == "D4"
        assert (
            c.execute(
                "SELECT count(*) AS n FROM events WHERE run_id=%s AND kind='placement.approved'",
                (run,),
            ).fetchone()["n"]
            == 1
        )
    assert after["revision"] == 1
    assert after["containers"] == before["containers"]
    assert by_id(after["jobs"], "MV-002")["source_id"] == choice["destination"]
    assert (
        by_id(after["jobs"], "MV-013")["placement_basis"]["proposal_id"] == result["id"]
    )
    with pytest.raises(RuleError, match="stale"):
        apply(after, result, choice["destination"], [])
    with pytest.raises(RuleError, match="State changed"):
        create(store, run, 0, "MV-013")


def test_rejected_destination_rolls_back_approval(db):
    store, run = db
    standard_fixture(store, run)
    result = create(store, run, 0, "MV-013")
    ident = str(uuid.uuid4())
    # Existing location outside the saved candidates: relational FK alone is insufficient.
    store.enqueue(
        run,
        dict(
            command_id=ident,
            expected_revision=0,
            action="approve_placement",
            plan_id=result["id"],
            destination_id="VESSEL-1",
        ),
        "operator",
    )
    drain(store)
    with store.connect() as c:
        assert (
            c.execute("SELECT status FROM commands WHERE id=%s", (ident,)).fetchone()[
                "status"
            ]
            == "rejected"
        )
        p = c.execute(
            "SELECT approved_command FROM placement_proposals WHERE id=%s",
            (result["id"],),
        ).fetchone()
        assert p["approved_command"] is None
    assert store.read(run)["revision"] == 0


def test_no_safe_stack_is_an_explicit_result(db):
    store, run = db
    standard_fixture(store, run)
    with store.connect() as c:
        # Reserve all remaining space by shrinking capacity to observed occupancy.
        c.execute(
            "UPDATE locations l SET capacity=(SELECT count(*) FROM containers c WHERE c.run_id=l.run_id AND c.location_id=l.id) WHERE run_id=%s AND kind='yard'",
            (run,),
        )
    result = create(store, run, 0, "MV-013")
    assert result["recommended"] is None
    assert not any(c["validation"] == "passed" for c in result["candidates"])
    assert all(f["excluded_reason"] for f in result["facts"])


def test_queued_incoming_work_consumes_capacity_and_cross_run_rejects(db):
    from app.placement_store import approval

    store, run = db
    standard_fixture(store, run)
    with store.connect() as c:
        c.execute("UPDATE locations SET capacity=6 WHERE run_id=%s AND id='D4'", (run,))
        c.execute(
            "UPDATE move_jobs SET target_id='D4' WHERE run_id=%s AND id='MV-014'",
            (run,),
        )
        rows = c.execute(
            (ROOT / "sql/placement_candidates.sql").read_text(),
            dict(run=run, job="MV-013"),
        ).fetchall()
        row = next(r for r in rows if r["destination"] == "D4")
        assert row["incoming"] >= 1
        assert row["free_slots"] <= 0
        assert row["excluded_reason"] == "No uncommitted capacity"
        with pytest.raises(RuleError, match="missing"):
            approval(
                c, "different-run", store.read(run, c), "missing-id", "D3", "unused"
            )


def test_clients_cannot_submit_their_own_validated_candidate():
    from app.api import Command
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Command(
            command_id="test-command",
            expected_revision=0,
            action="approve_placement",
            plan_id="fake",
            destination_id="D3",
            placement={"validation": "passed"},
        )
