import json
from copy import deepcopy
import pytest
from app.diagnosis import diagnose, describe_visit
from app.domain import by_id, RuleError
from test_datasets import db, advance


def cargo(report, id):
    return next(r for r in report["manifest"] if r["container_id"] == id)


def test_readiness_denominators_and_expected_upstream_transfer(db):
    store, create = db
    run = create("baseline-shift")
    report = diagnose(store, run)
    assert sum(d["total"] for d in report["departures"]) == 24
    for d in report["departures"]:
        assert d["total"] == sum(
            d[k]
            for k in (
                "on_time",
                "late",
                "ready",
                "underway",
                "blocked",
                "review",
                "missed",
            )
        )
    a = cargo(report, "CT-0121")
    assert a["job_ids"] == ["MV-001", "MV-013"]
    assert a["next_job_id"] == "MV-013" and a["readiness"] == "Next move ready"
    incoming = cargo(report, "CT-0139")
    assert incoming["mismatches"] == []
    assert any(
        i["code"] == "awaiting_transfer" for j in incoming["chain"] for i in j["issues"]
    )
    held = cargo(report, "CT-0125")
    assert held["readiness"] == "Waiting / blocked"
    assert any(
        i["facts"].get("released") is False for j in held["chain"] for i in j["issues"]
    )
    assert report["receipts"] == []


def test_corrected_position_traces_across_cargo_and_keeps_history(db):
    store, create = db
    run = create()
    before = diagnose(store, run, 0)
    advance(store, run, 5)
    after = diagnose(store, run)
    for id in ("CT-0121", "CT-0122"):
        r = cargo(after, id)
        assert r["readiness"] == "Needs review"
        assert r["mismatches"][0]["job_id"] == "MV-013"
        issue = next(
            i for d in r["chain"] for i in d["issues"] if i["code"] == "plan_mismatch"
        )
        assert issue["facts"]["location_id"] == "A2"
        assert (
            issue["facts"]["accepted_observations"]["CT-0122/container.position"][
                "received_minute"
            ]
            == 5
        )
    historic = diagnose(store, run, 0)
    assert historic["manifest"] == before["manifest"]
    assert historic["departures"] == before["departures"]
    assert historic["calendar"] == before["calendar"]
    assert historic["receipts"] == [] and historic["historical"]
    assert len(after["receipts"]) == 6
    assert all(r["applied_revision"] <= after["revision"] for r in after["receipts"])
    assert all(j["status"] != "completed" for j in cargo(after, "CT-0121")["chain"])


def test_dependency_diamond_does_not_double_count(db):
    store, create = db
    run = create("baseline-shift")
    with store.connect() as c:
        state = store.read(run, c, lock=True)
        by_id(state["jobs"], "MV-001")["dependencies"].append("MV-002")
        state["revision"] += 1
        store.persist(c, run, state, [], None)
    report = diagnose(store, run)
    row = cargo(report, "CT-0121")
    assert row["job_ids"] == ["MV-001", "MV-002", "MV-013"]
    assert len({d["job_id"] for d in row["chain"]}) == 3
    assert (
        next(d for d in report["departures"] if d["commitment_id"] == "NORTH-RAIL")[
            "total"
        ]
        == 6
    )


def test_cycle_is_visible_and_sql_terminates(db):
    store, create = db
    run = create("baseline-shift")
    with store.connect() as c:
        state = store.read(run, c, lock=True)
        by_id(state["jobs"], "MV-013")["dependencies"].append("MV-001")
        state["revision"] += 1
        store.persist(c, run, state, [], None)
    row = cargo(diagnose(store, run), "CT-0121")
    assert row["readiness"] == "Needs review"
    assert any("cycle" in x for x in row["integrity"])


def test_missing_delivery_is_not_ready(db):
    store, create = db
    run = create("baseline-shift")
    state = store.read(run)
    row = deepcopy(cargo(diagnose(store, run), "CT-0121"))
    for key in (
        "readiness",
        "next_job_id",
        "chain",
        "integrity",
        "attention",
        "cutoff",
    ):
        row.pop(key)
    row["final_ids"] = []
    assert describe_visit(state, row)["readiness"] == "Needs review"


def test_cutoff_and_outage_are_distinct_from_prediction(db):
    store, create = db
    run = create("impossible-cutoff")
    advance(store, run, 5)
    report = diagnose(store, run)
    assert (
        next(d for d in report["departures"] if d["commitment_id"] == "NORTH-RAIL")[
            "missed"
        ]
        == 6
    )
    run = create("equipment-outage")
    advance(store, run, 10)
    report = diagnose(store, run)
    lane = next(e for e in report["calendar"] if e["equipment_id"] == "YC-1")
    assert lane["status"] == "failed"
    assert lane["windows"][0][
        "permits_dispatch"
    ]  # shift time is not physical availability
    assert all(
        a["end"] <= report["minute"] for e in report["calendar"] for a in e["activity"]
    )
    assert len(report["receipts"]) == 1  # no future repair leakage


def test_diagnosis_is_read_only_and_revision_checked(db):
    store, create = db
    run = create("baseline-shift")
    before = store.read(run)
    diagnose(store, run)
    assert before == store.read(run)
    with pytest.raises(RuleError, match="Snapshot"):
        diagnose(store, run, 999)
    with pytest.raises(RuleError, match="Run"):
        diagnose(store, "does-not-exist")
