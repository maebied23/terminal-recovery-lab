"""Versioned file inputs -> validated operational state, without runtime seed code."""

import csv
import hashlib
import json
import math
import logging
import re
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from psycopg.types.json import Jsonb
from psycopg.types.range import Range
from .domain import RuleError, validate, eligible_equipment

ROOT = Path(__file__).resolve().parents[1] / "datasets"
LOG = logging.getLogger("terminal.datasets")
PACKS = (
    "baseline-shift",
    "movement-shift",
    "normal-shift",
    "equipment-outage",
    "imperfect-information",
    "impossible-cutoff",
)
SCHEMAS = {
    "locations": "id kind zone capacity:int block x:float y:float label",
    "equipment": "id kind zone status x:float y:float",
    "containers": "id weight_t:float",
    "visits": "id container_id commitment_id flow released:bool hold_reason",
    "inventory": "container_id location_id tier:int observed_at source",
    "commitments": "id kind location_id cutoff:int capacity:int arrival:int status",
    "work_orders": "id container_id source_id target_id kind equipment_id duration:int deadline:int created_order:int travel_minutes:int visit_id",
    "dependencies": "job_id predecessor_id reason kind origin basis_revision:int",
    "equipment_availability": "equipment_id start_minute:int end_minute:int source",
    "identities": "source external_id kind entity_id",
}


class PackError(RuleError):
    def __init__(self, message):
        super().__init__(message)


def minute_of(value, start):
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    origin = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if observed.tzinfo is None or origin.tzinfo is None:
        raise ValueError("A timezone offset is required")
    minutes = (observed - origin).total_seconds() / 60
    if not math.isfinite(minutes) or not minutes.is_integer():
        raise ValueError("Observations must align to whole simulated minutes")
    return int(minutes)


def typed(name, rows):
    schema = {
        p.split(":")[0]: p.split(":")[1] if ":" in p else "str"
        for p in SCHEMAS[name].split()
    }
    result = []
    for n, row in enumerate(rows, 2):
        if set(row) != set(schema):
            raise PackError(
                f"{name}.csv row {n}: columns differ from the input contract"
            )
        converted = {}
        for key, kind in schema.items():
            value = row[key]
            try:
                if value is None:
                    raise ValueError()
                if kind == "bool":
                    if str(value).lower() not in ("true", "false"):
                        raise ValueError()
                    value = str(value).lower() == "true"
                elif kind == "int":
                    if not re.fullmatch(r"-?\d+", str(value)):
                        raise ValueError()
                    value = int(value)
                elif kind == "float":
                    value = float(value)
                    if not math.isfinite(value):
                        raise ValueError()
                else:
                    value = str(value)
                    if len(value) > 500:
                        raise ValueError()
                converted[key] = value
            except (TypeError, ValueError):
                raise PackError(f"{name}.csv row {n}: invalid {key} ({kind})") from None
        result.append(converted)
    return result


def unique(rows, key, name):
    values = [r[key] for r in rows]
    if any(not x for x in values) or len(set(values)) != len(values):
        raise PackError(f"{name}: missing or duplicate {key}")
    return {r[key]: r for r in rows}


def load_pack(pack_id):
    if pack_id not in PACKS:
        raise PackError("Unknown input pack")
    folder = ROOT / pack_id
    try:
        manifest = json.loads((folder / "manifest.json").read_text())
        if (
            manifest["schema_version"] != 1
            or manifest["pack_id"] != pack_id
            or manifest["base"] != "baseline-shift"
        ):
            raise PackError("Unsupported manifest identity or schema")
        if (
            manifest["units"] != {"time": "minute", "weight": "tonne"}
            or manifest["timezone"] != "UTC"
        ):
            raise PackError("This contract requires UTC, minutes and tonnes")
        minute_of(manifest["shift_start"], manifest["shift_start"])
        origin = datetime.fromisoformat(manifest["shift_start"].replace("Z", "+00:00"))
        if (
            origin.hour != 8
            or origin.minute
            or origin.second
            or origin.utcoffset().total_seconds() != 0
        ):
            raise PackError("The current Northstar clock contract starts at 08:00 UTC")
        if manifest["seed"] != 42 or manifest["resource_model"] != "coordinated-v2":
            raise PackError("Unsupported seed or resource contract")
        if manifest["authority"] != {
            "equipment.status": "fleet",
            "container.position": "inventory",
            "container.release": "authority",
        }:
            raise PackError("Unsupported source authority contract")
        expected = {name + ".csv" for name in SCHEMAS}
        if set(manifest["base_files"]) != expected or set(manifest["files"]) != (
            {"changes.json", "events.jsonl", "movement.json"}
            if manifest.get("movement_version")
            else {"changes.json", "events.jsonl"}
        ):
            raise PackError("Incomplete or unexpected file list")
        for directory, entries in (
            (ROOT / "baseline-shift", manifest["base_files"]),
            (folder, manifest["files"]),
        ):
            for name, digest in entries.items():
                if (
                    hashlib.sha256((directory / name).read_bytes()).hexdigest()
                    != digest
                ):
                    raise PackError(
                        f"{name}: checksum mismatch; regenerate or explicitly reseal the input pack"
                    )
        raw = {}
        for name in SCHEMAS:
            with (ROOT / "baseline-shift" / (name + ".csv")).open(newline="") as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames != [
                    p.split(":")[0] for p in SCHEMAS[name].split()
                ]:
                    raise PackError(f"{name}.csv: unexpected or duplicate headers")
                raw[name] = list(reader)
                if not raw[name] or len(raw[name]) > 10000:
                    raise PackError(
                        f"{name}.csv: pack must contain 1–10000 rows per table"
                    )
        original = deepcopy(raw)
        changes = json.loads((folder / "changes.json").read_text())
        for change in changes:
            table = change["table"]
            if table not in ("inventory", "visits", "work_orders", "commitments"):
                raise PackError("Unsupported variation table")
            key = "container_id" if table == "inventory" else "id"
            matches = [r for r in raw[table] if r[key] == change["key"]]
            if len(matches) != 1:
                raise PackError(
                    f"Variation target missing or ambiguous: {table} {change['key']}"
                )
            if change.get("delete"):
                if table != "work_orders":
                    raise PackError(
                        "Only work orders can be removed in this variation contract"
                    )
                raw[table].remove(matches[0])
                raw["dependencies"] = [
                    d
                    for d in raw["dependencies"]
                    if change["key"] not in (d["job_id"], d["predecessor_id"])
                ]
            else:
                if key in change["set"]:
                    raise PackError("Variations cannot change identity")
                matches[0].update(change["set"])
                if table == "commitments" and "cutoff" in change["set"]:
                    # The outbound delivery's deadline comes from its commitment.
                    for j in raw["work_orders"]:
                        visit = next(
                            (v for v in raw["visits"] if v["id"] == j["visit_id"]), None
                        )
                        if (
                            visit
                            and visit["commitment_id"] == change["key"]
                            and j["target_id"] == matches[0]["location_id"]
                        ):
                            j["deadline"] = change["set"]["cutoff"]
        data = {name: typed(name, rows) for name, rows in raw.items()}
        state = assemble(data)
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest()
        receipts = [
            json.loads(line)
            for line in (folder / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        for r in receipts:
            if (
                set(r) != {"receive_minute", "event"}
                or type(r["receive_minute"]) is not int
                or not 1 <= r["receive_minute"] <= 10080
                or not isinstance(r["event"], dict)
            ):
                raise PackError(
                    "Event delivery must have an envelope and a receive minute within one week"
                )
        state["dataset"] = {
            "pack_id": pack_id,
            "title": manifest["title"],
            "digest": digest,
            "shift_start": manifest["shift_start"],
            "authority": manifest["authority"],
        }
        state["source_identities"] = data["identities"]
        state["availability"] = data["equipment_availability"]
        # Initial observed positions are evidence; subsequent simulator moves supersede them.
        state["position_observed"] = {
            r["container_id"]: minute_of(r["observed_at"], manifest["shift_start"])
            for r in data["inventory"]
        }
        if any(t != 0 for t in state["position_observed"].values()):
            raise PackError("Starting inventory must be observed at the shift start")
        if manifest.get("movement_version"):
            from .movement import install

            install(state, json.loads((folder / "movement.json").read_text()))
            validate(state)
        return dict(
            manifest=manifest,
            state=state,
            raw=original,
            changes=changes,
            receipts=receipts,
            digest=digest,
            counts={k: len(v) for k, v in data.items()},
        )
    except (KeyError, ValueError, TypeError, OSError, RecursionError) as exc:
        raise PackError(f"Invalid input pack: {exc}") from exc


def assemble(data):
    locations = unique(data["locations"], "id", "locations")
    equipment = unique(data["equipment"], "id", "equipment")
    containers = unique(data["containers"], "id", "containers")
    visits = unique(data["visits"], "id", "visits")
    cargo_visits = unique(
        data["visits"], "container_id", "visits (one current visit per container)"
    )
    positions = unique(data["inventory"], "container_id", "inventory")
    commitments = unique(data["commitments"], "id", "commitments")
    jobs = unique(data["work_orders"], "id", "work orders")
    if set(containers) != set(cargo_visits) or set(containers) != set(positions):
        raise PackError(
            "Every container needs exactly one current visit and inventory position"
        )
    for l in locations.values():
        if (
            l["capacity"] <= 0
            or l["kind"] not in ("yard", "vessel", "gate", "truck", "rail")
            or l["zone"] not in ("west", "east", "all")
        ):
            raise PackError("Invalid location capacity/kind/zone")
    for location in locations.values():
        if location["kind"] == "yard":
            tiers = sorted(
                p["tier"]
                for p in positions.values()
                if p["location_id"] == location["id"]
            )
            if tiers != list(range(len(tiers))):
                raise PackError(
                    "Yard inventory tiers must be contiguous from zero, without gaps"
                )
    for e in equipment.values():
        if (
            e["kind"] not in ("yard", "quay", "tractor", "gate")
            or e["status"] not in ("available", "failed")
            or e["zone"] not in ("west", "east", "all")
        ):
            raise PackError("Invalid equipment kind/status/zone")
        e["job_id"] = None
    for co in commitments.values():
        if (
            co["location_id"] not in locations
            or not 0 <= co["arrival"] <= co["cutoff"]
            or co["capacity"] <= 0
            or co["status"] != "scheduled"
        ):
            raise PackError("Invalid commitment window/location/status")
    for c in containers.values():
        visit = cargo_visits[c["id"]]
        pos = positions[c["id"]]
        if c["weight_t"] <= 0 or pos["tier"] < 0 or pos["location_id"] not in locations:
            raise PackError("Invalid cargo weight, tier or position")
        if pos["tier"] >= locations[pos["location_id"]]["capacity"]:
            raise PackError("Tier exceeds location capacity")
        c.update(
            visit_id=visit["id"],
            commitment_id=visit["commitment_id"] or None,
            flow=visit["flow"],
            released=visit["released"],
            hold_reason=visit["hold_reason"] or None,
            location_id=pos["location_id"],
            tier=pos["tier"],
            job_id=None,
        )
    for j in jobs.values():
        if (
            j["visit_id"] not in visits
            or visits[j["visit_id"]]["container_id"] != j["container_id"]
        ):
            raise PackError(f"{j['id']}: work order belongs to a different cargo visit")
        if (
            j["duration"] <= 0
            or j["travel_minutes"] < 0
            or j["deadline"] < 0
            or j["kind"] not in ("rehandle", "retrieve", "receive", "load", "discharge")
        ):
            raise PackError("Invalid work type or timing")
        j.update(
            status="queued",
            remaining=0,
            started_at=None,
            completed_at=None,
            resources=[],
            release_required=j["kind"] in ("retrieve", "load"),
            dependencies=[],
            dependency_details={},
        )
    for d in data["dependencies"]:
        if d["job_id"] not in jobs or d["predecessor_id"] not in jobs:
            raise PackError("Dependency refers to missing work")
        j = jobs[d["job_id"]]
        j["dependencies"].append(d["predecessor_id"])
        j["dependency_details"][d["predecessor_id"]] = {
            k: v for k, v in d.items() if k not in ("job_id", "predecessor_id")
        }
    for e in equipment:
        windows = sorted(
            (w for w in data["equipment_availability"] if w["equipment_id"] == e),
            key=lambda w: w["start_minute"],
        )
        if not windows:
            raise PackError(f"Missing availability for {e}")
        end = -1
        for w in windows:
            if (
                w["start_minute"] < 0
                or w["end_minute"] <= w["start_minute"]
                or w["start_minute"] < end
            ):
                raise PackError(f"Invalid or overlapping availability for {e}")
            end = w["end_minute"]
    if any(w["equipment_id"] not in equipment for w in data["equipment_availability"]):
        raise PackError("Availability refers to unknown equipment")
    identities = set()
    for r in data["identities"]:
        if (r["source"], r["external_id"]) in identities:
            raise PackError("Ambiguous external identity")
        identities.add((r["source"], r["external_id"]))
        if r["kind"] not in ("equipment", "container") or r["entity_id"] not in (
            equipment if r["kind"] == "equipment" else containers
        ):
            raise PackError("External identity refers to unknown entity")
    state = dict(
        revision=0,
        minute=0,
        seed=42,
        policy="fifo",
        running=False,
        speed=1,
        profile="standard",
        locations=list(locations.values()),
        equipment=list(equipment.values()),
        containers=list(containers.values()),
        jobs=list(jobs.values()),
        commitments=list(commitments.values()),
        observations=[],
        plan_id=None,
        duration_factor=1.0,
        data_mode="synthetic",
        resource_model="coordinated-v2",
    )
    validate(state)
    if len({j["created_order"] for j in jobs.values()}) != len(jobs) or any(
        j["created_order"] < 0 for j in jobs.values()
    ):
        raise PackError("Work orders need distinct nonnegative creation order")
    for j in jobs.values():
        if not any(e["id"] == j["equipment_id"] for e in eligible_equipment(state, j)):
            raise PackError(
                f"{j['id']}: assigned equipment cannot handle this work type/location"
            )
        seen = set()

        def upstream(id):
            for d in jobs[id]["dependencies"]:
                if d not in seen:
                    seen.add(d)
                    upstream(d)

        upstream(j["id"])
        if containers[j["container_id"]]["location_id"] != j["source_id"] and not any(
            jobs[d]["container_id"] == j["container_id"]
            and jobs[d]["target_id"] == j["source_id"]
            for d in seen
        ):
            raise PackError(
                f"{j['id']}: no predecessor delivers this cargo to its planned pickup"
            )
    # Every committed visit needs a terminal delivery, even if preceding work exists.
    for c in containers.values():
        if c["commitment_id"] and not any(
            j["container_id"] == c["id"]
            and j["target_id"] == commitments[c["commitment_id"]]["location_id"]
            for j in jobs.values()
        ):
            raise PackError(f"{c['id']}: no work delivers to its commitment")
    return state


def catalog():
    result = []
    for id in PACKS:
        try:
            p = load_pack(id)
            result.append(
                dict(
                    id=id,
                    title=p["manifest"]["title"],
                    description=p["manifest"]["description"],
                    valid=True,
                    digest=p["digest"],
                    counts=p["counts"],
                    events=len(p["receipts"]),
                    changes=p["changes"],
                )
            )
        except RuleError as exc:
            result.append(dict(id=id, title=id, valid=False, error=str(exc)))
    return result


def import_pack(store, pack_id, request_id, expected_digest):
    p = load_pack(pack_id)
    if p["digest"] != expected_digest:
        raise PackError("Input pack changed after preview; refresh and review it again")
    run = "data-" + str(uuid.UUID(request_id))
    with store.connect() as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (run,))
        existing = c.execute(
            "SELECT digest FROM dataset_imports WHERE run_id=%s", (run,)
        ).fetchone()
        if existing:
            if existing["digest"] != p["digest"]:
                raise PackError("Import request ID reused for different data")
            return dict(id=run, duplicate=True)
        store.create_run(c, run, p["manifest"]["title"] + " · imported", p["state"])
        c.execute(
            "INSERT INTO dataset_imports(run_id,pack_id,digest,manifest,validation) VALUES(%s,%s,%s,%s,%s)",
            (
                run,
                pack_id,
                p["digest"],
                Jsonb(p["manifest"]),
                Jsonb(
                    dict(counts=p["counts"], changes=p["changes"], status="validated")
                ),
            ),
        )
        with c.cursor().copy(
            "COPY dataset_rows(run_id,file_name,row_number,raw) FROM STDIN"
        ) as copy:
            for name, rows in p["raw"].items():
                for i, row in enumerate(rows, 2):
                    copy.write_row((run, name + ".csv", i, Jsonb(row)))
            for i, row in enumerate(p["changes"], 1):
                copy.write_row((run, "changes.json", i, Jsonb(row)))
        for w in p["state"]["availability"]:
            c.execute(
                "INSERT INTO equipment_windows VALUES(%s,%s,%s,%s)",
                (
                    run,
                    w["equipment_id"],
                    Range(w["start_minute"], w["end_minute"], "[)"),
                    w["source"],
                ),
            )
        for r in p["state"]["source_identities"]:
            c.execute(
                "INSERT INTO source_identities VALUES(%s,%s,%s,%s,%s)",
                (run, r["source"], r["external_id"], r["kind"], r["entity_id"]),
            )
        for i, r in enumerate(p["receipts"], 1):
            c.execute(
                "INSERT INTO feed_receipts(run_id,ordinal,receive_minute,envelope) VALUES(%s,%s,%s,%s)",
                (run, i, r["receive_minute"], Jsonb(r["event"])),
            )
    LOG.info("dataset_imported run=%s pack=%s digest=%s", run, pack_id, p["digest"])
    return dict(id=run, duplicate=False)
