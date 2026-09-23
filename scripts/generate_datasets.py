"""Author repeatable machine-readable CSV/JSON input packs, not Excel workbooks.

Only this authoring tool reads seed_state. Runtime imports read files exclusively.
Run from the repository root: .venv/bin/python -m scripts.generate_datasets
"""

import csv
import hashlib
import json
from pathlib import Path
from app.domain import seed_state

ROOT = Path(__file__).resolve().parents[1] / "datasets"


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def event(
    id,
    observed,
    received,
    value,
    sequence,
    kind="equipment.status",
    external="crane-west-1",
    source="fleet",
):
    return dict(
        receive_minute=received,
        event=dict(
            source=source,
            event_id=id,
            external_id=external,
            kind=kind,
            observed_at=f"2026-09-20T08:{observed:02d}:00+00:00",
            sequence=sequence,
            value=value,
        ),
    )


def generate():
    s = seed_state()
    base = ROOT / "baseline-shift"
    base.mkdir(parents=True, exist_ok=True)
    tables = {
        "locations.csv": s["locations"],
        "equipment.csv": [
            {k: v for k, v in e.items() if k != "job_id"} for e in s["equipment"]
        ],
        "containers.csv": [
            dict(id=c["id"], weight_t=c["weight_t"]) for c in s["containers"]
        ],
        "visits.csv": [
            dict(
                id=c["visit_id"],
                container_id=c["id"],
                commitment_id=c["commitment_id"] or "",
                flow=c["flow"],
                released=str(c["released"]).lower(),
                hold_reason=c["hold_reason"] or "",
            )
            for c in s["containers"]
        ],
        "inventory.csv": [
            dict(
                container_id=c["id"],
                location_id=c["location_id"],
                tier=c["tier"],
                observed_at="2026-09-20T08:00:00Z",
                source="inventory",
            )
            for c in s["containers"]
        ],
        "commitments.csv": s["commitments"],
        "work_orders.csv": [
            {
                k: j[k]
                for k in (
                    "id",
                    "container_id",
                    "source_id",
                    "target_id",
                    "kind",
                    "equipment_id",
                    "duration",
                    "deadline",
                    "created_order",
                    "travel_minutes",
                )
            }
            | {
                "visit_id": next(
                    c["visit_id"]
                    for c in s["containers"]
                    if c["id"] == j["container_id"]
                )
            }
            for j in s["jobs"]
        ],
        "dependencies.csv": [
            dict(job_id=j["id"], predecessor_id=d, **j["dependency_details"][d])
            for j in s["jobs"]
            for d in j["dependencies"]
        ],
        "equipment_availability.csv": [
            dict(
                equipment_id=e["id"],
                start_minute=0,
                end_minute=240,
                source="shift-roster",
            )
            for e in s["equipment"]
        ],
        "identities.csv": [
            dict(
                source="fleet",
                external_id="crane-west-1",
                kind="equipment",
                entity_id="YC-1",
            ),
            dict(
                source="inventory",
                external_id="box-121",
                kind="container",
                entity_id="CT-0121",
            ),
            dict(
                source="inventory",
                external_id="box-122",
                kind="container",
                entity_id="CT-0122",
            ),
            dict(
                source="authority",
                external_id="visit-125",
                kind="container",
                entity_id="CT-0125",
            ),
        ],
    }
    for name, rows in tables.items():
        write_csv(base / name, rows)
    configs = {
        "baseline-shift": (
            "North Rail baseline",
            "Reproduces the existing starting state, including its known access move.",
            [],
            [],
        ),
        "normal-shift": (
            "Accessible cargo",
            "Same commitments; remove the known cover and release the held cargo.",
            [
                dict(
                    table="inventory",
                    key="CT-0122",
                    set={"location_id": "A2", "tier": 5},
                ),
                dict(
                    table="visits",
                    key="VIS-0125",
                    set={"released": "true", "hold_reason": ""},
                ),
                dict(
                    table="work_orders",
                    key="MV-002",
                    set={"source_id": "A2", "equipment_id": "YC-1"},
                ),
                dict(table="work_orders", key="MV-013", delete=True),
            ],
            [],
        ),
        "equipment-outage": (
            "Yard crane outage",
            "Fleet feed reports Yard crane 1 failed at 08:10; repair at 08:25.",
            [],
            [
                event("failure-1", 10, 10, "failed", 1),
                event("repair-1", 25, 25, "available", 2),
            ],
        ),
        "imperfect-information": (
            "Delayed and conflicting observations",
            "Duplicates, an old observation, a corrected position and invalid records test reconciliation.",
            [],
            [
                event("failure-1", 2, 2, "failed", 2),
                event("failure-1", 2, 3, "failed", 2),
                event("old-availability", 1, 4, "available", 1),
                event("failure-1", 2, 5, "available", 2),
                event("unknown", 5, 5, "failed", 1, external="unknown-crane"),
                event(
                    "position-correction",
                    3,
                    5,
                    {"location_id": "A2", "tier": 5},
                    1,
                    kind="container.position",
                    external="box-122",
                    source="inventory",
                ),
                event(
                    "collision",
                    5,
                    6,
                    {"location_id": "A2", "tier": 4},
                    2,
                    kind="container.position",
                    external="box-122",
                    source="inventory",
                ),
                event(
                    "release-125",
                    5,
                    7,
                    True,
                    1,
                    kind="container.release",
                    external="visit-125",
                    source="authority",
                ),
            ],
        ),
        "impossible-cutoff": (
            "No time to recover",
            "North Rail closes at 08:01, before any required retrieval can finish.",
            [dict(table="commitments", key="NORTH-RAIL", set={"cutoff": 1})],
            [],
        ),
    }
    base_hashes = {
        name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in tables
    }
    for pack, (title, description, changes, events) in configs.items():
        folder = ROOT / pack
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "changes.json").write_text(json.dumps(changes, indent=2) + "\n")
        (folder / "events.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in events)
        )
        manifest = dict(
            schema_version=1,
            pack_id=pack,
            title=title,
            description=description,
            base="baseline-shift",
            generator="northstar-inputs-v1",
            seed=42,
            shift_start="2026-09-20T08:00:00Z",
            timezone="UTC",
            units={"time": "minute", "weight": "tonne"},
            resource_model="coordinated-v2",
            base_files=base_hashes,
            files={
                n: hashlib.sha256((folder / n).read_bytes()).hexdigest()
                for n in ("changes.json", "events.jsonl")
            },
            assumptions=[
                "Synthetic observations, not terminal telemetry.",
                "One current visit per container; repeated-visit execution is not supported yet.",
                "Availability windows permit dispatch; they are not job reservations.",
                "No geographic route network; travel remains the existing one-minute assumption.",
            ],
            authority={
                "equipment.status": "fleet",
                "container.position": "inventory",
                "container.release": "authority",
            },
        )
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Generated {len(configs)} input packs in {ROOT}")


if __name__ == "__main__":
    generate()
