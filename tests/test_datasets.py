import json
import uuid
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import pytest
import psycopg
from psycopg.types.range import Range
from app.datasets import (
    load_pack,
    import_pack,
    assemble,
    minute_of,
    PackError,
    catalog,
    typed,
)
from app.domain import seed_state, by_id, transition, blockers, RuleError
from app.store import Store
from app.feed import reconcile_due
from app.data_evidence import evidence


def test_baseline_parity_and_independent_variations():
    original = seed_state()
    loaded = load_pack("baseline-shift")["state"]
    for j in loaded["jobs"]:
        j.pop("visit_id")
    assert all(original[k] == loaded[k] for k in original)
    assert all(p["valid"] for p in catalog())
    normal = load_pack("normal-shift")["state"]
    assert len(normal["jobs"]) == 36
    assert not by_id(normal["jobs"], "MV-001")["dependencies"]
    assert by_id(normal["containers"], "CT-0125")["released"]
    impossible = load_pack("impossible-cutoff")["state"]
    assert by_id(impossible["commitments"], "NORTH-RAIL")["cutoff"] == 1
    assert by_id(impossible["jobs"], "MV-001")["deadline"] == 1
    assert "feed_receipts" not in loaded and "receipts" not in loaded


def test_timestamps_and_checksums(tmp_path, monkeypatch):
    assert minute_of("2026-09-20T10:05:00+02:00", "2026-09-20T08:00:00Z") == 5
    with pytest.raises(ValueError):
        minute_of("2026-09-20T08:00:00", "2026-09-20T08:00:00Z")
    from app import datasets
    import shutil

    shutil.copytree(datasets.ROOT, tmp_path / "packs")
    monkeypatch.setattr(datasets, "ROOT", tmp_path / "packs")
    (datasets.ROOT / "baseline-shift/inventory.csv").write_text("edited")
    with pytest.raises(PackError, match="checksum"):
        load_pack("baseline-shift")


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "missing_inventory",
        "wrong_visit",
        "orphan_pickup",
        "cycle",
        "capacity",
        "weight",
        "window",
        "fractional_integer",
        "stack_gap",
    ],
)
def test_invalid_relationships_and_data_are_rejected(fault):
    raw = deepcopy(load_pack("baseline-shift")["raw"])
    if fault == "duplicate":
        raw["containers"].append(raw["containers"][0])
    if fault == "missing_inventory":
        raw["inventory"].pop()
    if fault == "wrong_visit":
        raw["work_orders"][0]["visit_id"] = "VIS-0122"
    if fault == "orphan_pickup":
        raw["work_orders"][0]["source_id"] = "F4"
    if fault == "cycle":
        raw["dependencies"].append(
            dict(raw["dependencies"][0], job_id="MV-013", predecessor_id="MV-001")
        )
    if fault == "capacity":
        raw["locations"][0]["capacity"] = "1"
    if fault == "weight":
        raw["containers"][0]["weight_t"] = "NaN"
    if fault == "window":
        raw["equipment_availability"].append(raw["equipment_availability"][0])
    if fault == "stack_gap":
        raw["inventory"][0]["tier"] = "10"
    if fault == "fractional_integer":
        raw["inventory"][0]["tier"] = 1.4
    with pytest.raises(RuleError):
        assemble({k: typed(k, v) for k, v in raw.items()})


@pytest.fixture
def db():
    store = Store()
    store.initialize()
    runs = []

    def create(pack="imperfect-information", request_id=None):
        p = load_pack(pack)
        id = import_pack(store, pack, request_id or str(uuid.uuid4()), p["digest"])[
            "id"
        ]
        runs.append(id)
        return id

    yield store, create
    with store.connect() as c:
        for run in runs:
            for table in (
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
            ):
                c.execute(
                    f"DELETE FROM {table} WHERE {'id' if table=='runs' else 'run_id'}=%s",
                    (run,),
                )


def advance(store, run, minutes):
    with store.connect() as c:
        s = store.read(run, c, lock=True)
        ns, events = transition(
            s,
            dict(action="advance", minutes=minutes),
            lambda state: reconcile_due(c, run, state),
        )
        store.persist(c, run, ns, events, None)
    return store.read(run)


def test_atomic_import_dedup_and_foreign_visit(db):
    store, create = db
    run = create("baseline-shift")
    p = load_pack("baseline-shift")
    result = import_pack(store, "baseline-shift", run[5:], p["digest"])
    assert result["duplicate"]
    with pytest.raises(RuleError):
        import_pack(
            store, "equipment-outage", run[5:], load_pack("equipment-outage")["digest"]
        )
    with pytest.raises(RuleError, match="changed"):
        import_pack(store, "baseline-shift", str(uuid.uuid4()), "0" * 64)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with store.connect() as c:
            c.execute(
                "UPDATE move_jobs SET visit_id='VIS-0122' WHERE run_id=%s AND id='MV-001'",
                (run,),
            )
    assert by_id(store.read(run)["jobs"], "MV-001")["visit_id"] == "VIS-0121"
    with store.connect() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM dataset_rows WHERE run_id=%s", (run,)
            ).fetchone()["n"]
            > 400
        )


def test_availability_exclusion_and_boundary(db):
    store, create = db
    run = create("baseline-shift")
    with pytest.raises(psycopg.errors.ExclusionViolation):
        with store.connect() as c:
            c.execute(
                "INSERT INTO equipment_windows VALUES(%s,'YC-1',%s,'test')",
                (run, Range(5, 10, "[)")),
            )
    with store.connect() as c:
        c.execute(
            "INSERT INTO equipment_windows VALUES(%s,'YC-1',%s,'test')",
            (run, Range(240, 241, "[)")),
        )
    s = load_pack("baseline-shift")["state"]
    for w in s["availability"]:
        if w["equipment_id"] == "YC-1":
            w["end_minute"] = 1
    s["minute"] = 1
    assert "YC-1 outside published availability" in blockers(
        s, by_id(s["jobs"], "MV-001")
    )


def test_reconciliation_history_and_diagnosis(db):
    store, create = db
    run = create()
    initial = evidence(store, run, 0, "YC-1")
    assert initial["counts"]["awaiting_delivery"] == 8
    assert initial["receipts"] == []
    after = advance(store, run, 5)
    assert by_id(after["equipment"], "YC-1")["status"] == "failed"
    assert by_id(after["containers"], "CT-0122")["tier"] == 5
    assert by_id(after["containers"], "CT-0122")["location_id"] == "A2"
    report = evidence(store, run, 1, "YC-1")
    assert report["counts"] == dict(
        applied=2, quarantined=2, duplicates=1, stale=1, awaiting_delivery=2
    )
    assert report["impact"] and any(
        row["commitment_id"] == "NORTH-RAIL" for row in report["impact"]
    )
    assert all(row["cargo_visits"] <= row["moves"] for row in report["impact"])
    assert report["provenance"]["YC-1/equipment.status"]["event_id"] == "failure-1"
    assert Store().read(run)["input_provenance"] == after["input_provenance"]
    historical = evidence(store, run, 0, "YC-1")
    assert historical["receipts"] == [] and historical["impact"] is None
    assert (
        by_id(store.history(run, 0)["state"]["equipment"], "YC-1")["status"]
        == "available"
    )
    later = advance(store, run, 5)
    assert by_id(later["containers"], "CT-0122")["tier"] == 5  # collision refused
    assert by_id(later["containers"], "CT-0125")["released"]
    assert evidence(store, run, 2, "CT-0121")["counts"]["quarantined"] == 3


def test_no_future_event_leak_and_outage(db):
    store, create = db
    run = create("equipment-outage")
    before = advance(store, run, 5)
    assert by_id(before["equipment"], "YC-1")["status"] == "available"
    assert not before.get("input_provenance", {}).get("YC-1/equipment.status")
    after = advance(store, run, 5)
    assert by_id(after["equipment"], "YC-1")["status"] == "failed"
    assert evidence(store, run, 2, "YC-1")["counts"]["applied"] == 1
    # Pure forecast cannot consume external receipts from the database.
    forecast, _ = transition(before, dict(action="advance", minutes=5))
    assert by_id(forecast["equipment"], "YC-1")["status"] == "available"


def test_concurrent_receipt_processing_is_once(db):
    store, create = db
    run = create("equipment-outage")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: advance(store, run, 5), range(2)))
    r = evidence(store, run, None, "YC-1")
    assert r["revision"] == 2 and r["counts"]["applied"] == 1


def test_concurrent_import_retries_return_one_run(db):
    store, create = db
    request_id = str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: create("baseline-shift", request_id), range(2))
        )
    assert len(set(results)) == 1
    with store.connect() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM dataset_imports WHERE run_id=%s",
                (results[0],),
            ).fetchone()["n"]
            == 1
        )


def test_invalid_event_does_not_partially_change_state(db):
    store, create = db
    run = create()
    advance(store, run, 10)
    with store.connect() as c:
        row = c.execute(
            "SELECT * FROM feed_receipts WHERE run_id=%s AND ordinal=7", (run,)
        ).fetchone()
        assert row["status"] == "quarantined" and row["after_value"] is None
        assert "tier" in row["reason"]
    assert by_id(store.read(run)["containers"], "CT-0122")["tier"] == 5


def test_buried_position_correction_requires_stack_reconciliation(db):
    from psycopg.types.json import Jsonb

    store, create = db
    run = create("baseline-shift")
    envelope = dict(
        source="inventory",
        event_id="buried-correction",
        external_id="box-121",
        kind="container.position",
        observed_at="2026-09-20T08:01:00Z",
        sequence=1,
        value=dict(location_id="A2", tier=5),
    )
    with store.connect() as c:
        c.execute(
            "INSERT INTO feed_receipts(run_id,ordinal,receive_minute,envelope) VALUES(%s,1,1,%s)",
            (run, Jsonb(envelope)),
        )
    after = advance(store, run, 1)
    assert by_id(after["containers"], "CT-0121")["location_id"] == "A1"
    r = evidence(store, run, None, "CT-0121")
    assert r["counts"]["quarantined"] == 1
    assert "Buried" in r["receipts"][0]["reason"]


def test_cutoff_change_follows_visit_not_shared_destination(tmp_path, monkeypatch):
    import csv, hashlib, shutil
    from app import datasets

    shutil.copytree(datasets.ROOT, tmp_path / "packs")
    monkeypatch.setattr(datasets, "ROOT", tmp_path / "packs")

    def change_csv(name, mutate):
        path = datasets.ROOT / "baseline-shift" / name
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            header, rows = reader.fieldnames, list(reader)
        mutate(rows)
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)

    change_csv(
        "commitments.csv",
        lambda rows: rows.append(
            dict(next(r for r in rows if r["id"] == "NORTH-RAIL"), id="OTHER-RAIL")
        ),
    )

    def reassign(rows):
        next(r for r in rows if r["id"] == "VIS-0126")["commitment_id"] = "OTHER-RAIL"

    change_csv("visits.csv", reassign)
    manifest_path = datasets.ROOT / "impossible-cutoff/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for name in manifest["base_files"]:
        manifest["base_files"][name] = hashlib.sha256(
            (datasets.ROOT / "baseline-shift" / name).read_bytes()
        ).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    state = load_pack("impossible-cutoff")["state"]
    assert by_id(state["jobs"], "MV-001")["deadline"] == 1
    assert by_id(state["jobs"], "MV-006")["deadline"] == 42
