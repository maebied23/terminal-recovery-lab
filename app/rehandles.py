"""Bounded access planning. Proposals never move observed cargo."""

from copy import deepcopy
from hashlib import sha256
import json


def propose(s, job_id):
    from .domain import by_id, location, eligible_equipment, RuleError

    j = by_id(s["jobs"], job_id)
    if not j or j["status"] != "queued":
        raise RuleError("Select a queued pickup to plan access")
    cargo = by_id(s["containers"], j["container_id"])
    if (
        cargo["location_id"] != j["source_id"]
        or location(s, j["source_id"])["kind"] != "yard"
    ):
        raise RuleError(
            "Cargo must be observed at its yard pickup before planning access"
        )
    covers = sorted(
        [
            c
            for c in s["containers"]
            if c["location_id"] == cargo["location_id"] and c["tier"] > cargo["tier"]
        ],
        key=lambda c: -c["tier"],
    )
    if not covers:
        raise RuleError("This container is already accessible")
    if len(covers) > 8:
        raise RuleError("Access chain exceeds the eight-container planner")
    for cover in covers:
        existing = [
            x
            for x in s["jobs"]
            if x["container_id"] == cover["id"]
            and x["kind"] == "rehandle"
            and x["status"] != "completed"
        ]
        if existing:
            raise RuleError(
                f"Existing access work {existing[0]['id']} already moves {cover['id']}; inspect it instead"
            )
    shadow = deepcopy(s)
    moves = []
    for cover in covers:
        choices = []
        for loc in shadow["locations"]:
            if (
                loc["kind"] != "yard"
                or loc["id"] == j["source_id"]
                or loc["zone"] != location(s, j["source_id"])["zone"]
            ):
                continue
            occupants = [
                c for c in shadow["containers"] if c["location_id"] == loc["id"]
            ]
            reserved = sum(
                x["status"] == "running" and x["target_id"] == loc["id"]
                for x in s["jobs"]
            )
            if (
                len(occupants) + reserved >= loc["capacity"]
                or any(c["commitment_id"] for c in occupants)
                or any(
                    x["status"] == "queued" and x["target_id"] == loc["id"]
                    for x in s["jobs"]
                )
            ):
                continue
            choices.append(loc)
        if not choices:
            raise RuleError(
                f"No safe same-zone destination for {cover['id']}; no proposal created"
            )
        target = min(
            choices,
            key=lambda l: (
                sum(c["location_id"] == l["id"] for c in shadow["containers"]),
                abs(l["x"] - location(s, j["source_id"])["x"])
                + abs(l["y"] - location(s, j["source_id"])["y"]),
                l["id"],
            ),
        )
        trial = dict(
            j, kind="rehandle", target_id=target["id"], container_id=cover["id"]
        )
        equipment = [
            e
            for e in eligible_equipment(s, trial)
            if e["status"] == "available"
            and cover["weight_t"] <= e.get("lifting_capacity_t", 50)
        ]
        if not equipment:
            raise RuleError("No compatible available yard crane")
        moves.append(
            dict(
                container_id=cover["id"],
                source_id=j["source_id"],
                target_id=target["id"],
                equipment_id=min(equipment, key=lambda e: (bool(e["job_id"]), e["id"]))[
                    "id"
                ],
                reason=f"Clear access to {j['container_id']}; same-zone capacity and downstream obstruction checks passed",
            )
        )
        by_id(shadow["containers"], cover["id"])["location_id"] = target["id"]
    result = dict(
        job_id=job_id,
        base_revision=s["revision"],
        moves=moves,
        assumptions=[
            "Synthetic reach and 50 t lifting limits",
            "Whole-move reservations; no operator, hazmat or road-routing model",
            "Approval creates work, not physical movement",
        ],
    )
    result["token"] = sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def apply(s, job_id, token):
    from .domain import by_id, RuleError, validate

    p = propose(s, job_id)
    if p["token"] != token:
        raise RuleError("Access proposal is stale; preview again")
    target = by_id(s["jobs"], job_id)
    previous = None
    added = []
    for move in p["moves"]:
        n = max(int(x["id"].split("-")[-1]) for x in s["jobs"]) + 1
        jid = f"MV-{n:03}"
        job = dict(
            id=jid,
            container_id=move["container_id"],
            source_id=move["source_id"],
            target_id=move["target_id"],
            kind="rehandle",
            equipment_id=move["equipment_id"],
            status="queued",
            duration=3,
            remaining=0,
            deadline=target["deadline"],
            dependencies=[previous] if previous else [],
            dependency_details={},
            started_at=None,
            completed_at=None,
            resources=[],
            release_required=False,
            created_order=n,
            travel_minutes=1,
            origin="access planner",
            basis_revision=s["revision"],
        )
        if previous:
            job["dependency_details"][previous] = dict(
                kind="access",
                reason="Remove the upper cover first",
                origin="access planner",
                basis_revision=s["revision"],
            )
        for onward in s["jobs"]:
            if (
                onward["container_id"] == move["container_id"]
                and onward["status"] == "queued"
                and onward["source_id"] == move["source_id"]
            ):
                onward["source_id"] = move["target_id"]
                onward["dependencies"] = list(
                    dict.fromkeys(onward["dependencies"] + [jid])
                )
                onward.setdefault("dependency_details", {})[jid] = dict(
                    kind="sequence",
                    reason=f"Deliver {move['container_id']} to {move['target_id']}",
                    origin="access planner",
                    basis_revision=s["revision"],
                )
        s["jobs"].append(job)
        added.append(jid)
        previous = jid
    target["dependencies"] = list(dict.fromkeys(target["dependencies"] + [previous]))
    target.setdefault("dependency_details", {})[previous] = dict(
        kind="access",
        reason=f"Clear all {len(added)} blocking containers",
        origin="access planner",
        basis_revision=s["revision"],
    )
    validate(s)
    return p, added
