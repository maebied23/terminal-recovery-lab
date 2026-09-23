"""Versioned synthetic routes. Geometry is display-only; edge lengths have explicit units."""

from copy import deepcopy
import hashlib
import heapq
import json
import math
from .domain import RuleError, by_id

VERSION = "staged-routes-v1"
_ROUTE_CACHE = {}


def enabled(s):
    return s.get("movement", {}).get("version") == VERSION


def validate_network(net, s):
    if net.get("version") != VERSION or net.get("units") != "metres/minutes":
        raise RuleError("Unsupported movement model or units")
    nodes = {n["id"] for n in net["nodes"]}
    if (
        len(nodes) != len(net["nodes"])
        or not {l["id"] for l in s["locations"]} <= nodes
    ):
        raise RuleError("Duplicate or missing transport nodes")
    ids = set()
    for e in net["edges"]:
        if e["id"] in ids or e["source"] not in nodes or e["target"] not in nodes:
            raise RuleError("Invalid route identity/endpoints")
        ids.add(e["id"])
        if any(
            not isinstance(e[k], (int, float)) or not math.isfinite(e[k]) or e[k] <= 0
            for k in ("metres", "loaded_mpm", "empty_mpm")
        ):
            raise RuleError("Route costs must be finite and positive")
    for e in s["equipment"]:
        if (
            e["kind"] == "tractor"
            and net["initial_positions"].get(e["id"]) not in nodes
        ):
            raise RuleError("Tractor starting position is unknown")
    if any(
        type(net[k]) is not int or net[k] < 1
        for k in ("pickup_minutes", "setdown_minutes")
    ):
        raise RuleError("Handling minutes must be positive integers")


def install(s, net):
    validate_network(net, s)
    s["movement"] = deepcopy(net)
    s["movement"]["digest"] = hashlib.sha256(
        json.dumps(net, sort_keys=True).encode()
    ).hexdigest()
    for e in s["equipment"]:
        if e["kind"] == "tractor":
            e["node_id"] = net["initial_positions"][e["id"]]
    for c in s["containers"]:
        c["custody"] = dict(kind="location", id=c["location_id"])


def route(s, source, target, loaded=True):
    net = s["movement"]
    cache_key = (
        net["digest"],
        tuple(e["id"] for e in net["edges"] if e.get("closed")),
        source,
        target,
        loaded,
    )
    if cache_key in _ROUTE_CACHE:
        return deepcopy(_ROUTE_CACHE[cache_key])
    nodes = {n["id"] for n in net["nodes"]}
    if source not in nodes or target not in nodes:
        raise RuleError("Unknown transport position; inspect movement inputs")
    costs = [(0.0, source, (), 0.0)]
    seen = set()
    while costs:
        minutes, node, path, metres = heapq.heappop(costs)
        if node in seen:
            continue
        seen.add(node)
        if node == target:
            result = dict(
                source=source,
                target=target,
                edges=list(path),
                metres=round(metres, 3),
                minutes=math.ceil(minutes),
                loaded=loaded,
                digest=net["digest"],
            )
            if len(_ROUTE_CACHE) > 4096:
                _ROUTE_CACHE.clear()
            _ROUTE_CACHE[cache_key] = result
            return deepcopy(result)
        for e in sorted(net["edges"], key=lambda e: e["id"]):
            if (
                e["source"] == node
                and not e.get("closed")
                and "tractor" in e["compatible"]
            ):
                heapq.heappush(
                    costs,
                    (
                        minutes
                        + e["metres"] / e["loaded_mpm" if loaded else "empty_mpm"],
                        e["target"],
                        path + (e["id"],),
                        metres + e["metres"],
                    ),
                )
    raise RuleError(f"No open compatible route from {source} to {target}")


def stages(s, j, start, resources):
    tractors = [x for x in resources if by_id(s["equipment"], x)["kind"] == "tractor"]
    if len(tractors) != 1:
        raise RuleError("This movement template requires one terminal tractor")
    tractor = tractors[0]
    handlers = [x for x in resources if x != tractor]

    def handler(loc):
        l = by_id(s["locations"], loc)
        kind = (
            "yard"
            if l["kind"] in ("yard", "rail")
            else "quay" if l["kind"] == "berth" else None
        )
        # Service identities are canonical; endpoint handling remains a simplified model.
        if loc.startswith("VESSEL"):
            kind = "quay"
        compatible = [
            x
            for x in handlers
            if (kind is None or by_id(s["equipment"], x)["kind"] == kind)
            and (
                by_id(s["equipment"], x)["zone"] == "all"
                or l["zone"] == "all"
                or by_id(s["equipment"], x)["zone"] == l["zone"]
            )
        ]
        if not compatible:
            compatible = handlers if l["kind"] != "yard" else []
        if not compatible:
            raise RuleError(f"No endpoint handler for {loc}")
        return compatible[0]

    pickup, receiving = handler(j["source_id"]), handler(j["target_id"])
    empty = route(
        s, by_id(s["equipment"], tractor).get("node_id"), j["source_id"], False
    )
    loaded = route(s, j["source_id"], j["target_id"])
    factor = s.get("duration_factor", 1)
    parts = [
        ("empty", "Empty reposition", empty["minutes"], [tractor], empty),
        (
            "pickup",
            "Pickup and load",
            math.ceil(s["movement"]["pickup_minutes"] * factor),
            [pickup, tractor],
            None,
        ),
        ("transfer", "Loaded transfer", max(1, loaded["minutes"]), [tractor], loaded),
        (
            "setdown",
            "Unload and place",
            math.ceil(s["movement"]["setdown_minutes"] * factor),
            [receiving, tractor],
            None,
        ),
    ]
    result = []
    for kind, name, minutes, equipment, path in parts:
        if minutes <= 0:
            continue
        result.append(
            dict(
                kind=kind,
                name=name,
                start=start,
                end=start + minutes,
                resources=list(dict.fromkeys(equipment)),
                route=path,
            )
        )
        start += minutes
    return result


def make_row(s, j, start, resources, frozen=False):
    if frozen:
        parts = deepcopy(j["movement_stages"][j["stage_index"] :])
        cursor = start
        for i, p in enumerate(parts):
            length = j["stage_remaining"] if i == 0 else p["end"] - p["start"]
            p.update(start=cursor, end=cursor + length)
            cursor += length
    else:
        parts = stages(s, j, start, resources)
    return dict(
        job_id=j["id"],
        container_id=j["container_id"],
        visit_id=by_id(s["containers"], j["container_id"])["visit_id"],
        source_id=j["source_id"],
        target_id=j["target_id"],
        start=start,
        end=parts[-1]["end"],
        resources=list(resources),
        stages=parts,
        frozen=frozen,
        movement_version=VERSION,
        movement_digest=s["movement"]["digest"],
    )


def intervals(row):
    for p in row["stages"]:
        for eid in p.get("resources", row["resources"]):
            yield eid, p["start"], p["end"]


def calendar_ok(s, row):
    return (
        all(
            any(
                w["equipment_id"] == eid
                and w["start_minute"] <= a
                and b <= w["end_minute"]
                for w in s.get("availability", [])
            )
            for eid, a, b in intervals(row)
        )
        if "availability" in s
        else True
    )


def conflict(row, others):
    return any(
        e == f and a < d and c < b
        for e, a, b in intervals(row)
        for other in others
        for f, c, d in intervals(other)
    )


def position(s, path, progress):
    """Schematic position along the saved metric route; never telemetry."""
    distance = path["metres"] * max(0, min(1, progress))
    for eid in path["edges"]:
        edge = by_id(s["movement"]["edges"], eid)
        if distance <= edge["metres"]:
            a = by_id(s["movement"]["nodes"], edge["source"])
            b = by_id(s["movement"]["nodes"], edge["target"])
            f = distance / edge["metres"]
            return dict(
                x=a["x"] + (b["x"] - a["x"]) * f, y=a["y"] + (b["y"] - a["y"]) * f
            )
        distance -= edge["metres"]
    n = by_id(s["movement"]["nodes"], path["target"])
    return dict(x=n["x"], y=n["y"])


def unknown_completion(s, j):
    if j["status"] != "running" or not enabled(s):
        return False
    future = j.get("movement_stages", [])[j.get("stage_index", 0) :]
    return bool(j.get("waiting_reason")) or any(
        by_id(s["equipment"], e)["status"] == "failed"
        for p in future
        for e in p["resources"]
    )
