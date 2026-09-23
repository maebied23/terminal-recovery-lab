"""Reconcile delivered observations within the run's existing state transaction.

Future deliveries stay in PostgreSQL, outside planner snapshots. All attempts,
including conflicts and duplicates, remain evidence. No arbitrary field writes.
"""

from copy import deepcopy
from psycopg.types.json import Jsonb
from .datasets import minute_of
from .domain import RuleError, by_id, validate


def reconcile_due(connection, run, state):
    if "dataset" not in state:
        return []
    receipts = connection.execute(
        "SELECT * FROM feed_receipts WHERE run_id=%s AND status='pending' AND receive_minute<=%s ORDER BY receive_minute,ordinal FOR UPDATE",
        (run, state["minute"]),
    ).fetchall()
    events = []
    for receipt in receipts:
        envelope = receipt["envelope"]
        outcome, reason = "quarantined", "Invalid observation"
        entity_id = field = observed = before = after = None
        try:
            required = {
                "source",
                "event_id",
                "external_id",
                "kind",
                "observed_at",
                "sequence",
                "value",
            }
            if set(envelope) != required:
                raise RuleError("Envelope fields do not match the input contract")
            if any(
                not isinstance(envelope[k], str) or not 0 < len(envelope[k]) <= 120
                for k in ("source", "event_id", "external_id", "kind", "observed_at")
            ):
                raise RuleError("Invalid source, identity or timestamp")
            if type(envelope["sequence"]) is not int or envelope["sequence"] < 0:
                raise RuleError("A nonnegative source sequence is required")
            old = connection.execute(
                "SELECT e.canonical,r.entity_id,r.field,r.observed_minute FROM feed_events e JOIN feed_receipts r ON r.id=e.first_receipt WHERE e.run_id=%s AND e.source=%s AND e.event_id=%s",
                (run, envelope["source"], envelope["event_id"]),
            ).fetchone()
            if old:
                entity_id, field, observed = (
                    old["entity_id"],
                    old["field"],
                    old["observed_minute"],
                )
                if old["canonical"] != envelope:
                    raise RuleError(
                        "Source event ID reused with conflicting content; original retained"
                    )
                outcome, reason = (
                    "duplicate",
                    "Already received; no second state change",
                )
            else:
                connection.execute(
                    "INSERT INTO feed_events VALUES(%s,%s,%s,%s,%s)",
                    (
                        run,
                        envelope["source"],
                        envelope["event_id"],
                        Jsonb(envelope),
                        receipt["id"],
                    ),
                )
                mapping = next(
                    (
                        m
                        for m in state.get("source_identities", [])
                        if m["source"] == envelope["source"]
                        and m["external_id"] == envelope["external_id"]
                    ),
                    None,
                )
                if not mapping:
                    raise RuleError(
                        "Unknown external identity; add an explicit source mapping"
                    )
                entity_id = mapping["entity_id"]
                field = envelope["kind"]
                if state["dataset"]["authority"].get(field) != envelope["source"]:
                    raise RuleError("This source is not authoritative for this field")
                observed = minute_of(
                    envelope["observed_at"], state["dataset"]["shift_start"]
                )
                if not 0 <= observed <= receipt["receive_minute"]:
                    raise RuleError(
                        "Observation is outside the known shift time; future observations cannot apply"
                    )
                key = f"{entity_id}/{field}"
                head = state.get("input_provenance", {}).get(key)
                if head and (
                    envelope["sequence"] <= head["sequence"]
                    or observed < head["observed_minute"]
                ):
                    outcome, reason = (
                        "stale",
                        "Older event time or non-increasing source sequence; current state retained",
                    )
                else:
                    candidate = deepcopy(state)
                    collection = (
                        "equipment" if field == "equipment.status" else "containers"
                    )
                    obj = by_id(candidate[collection], entity_id)
                    if not obj:
                        raise RuleError("Mapped identity has the wrong entity type")
                    value = envelope["value"]
                    if field == "equipment.status":
                        if value not in ("available", "failed"):
                            raise RuleError(
                                "Equipment status must be available or failed"
                            )
                        # Manual scenario observations are also facts: an older feed cannot erase one.
                        last = max(
                            (
                                o["valid_minute"]
                                for o in state["observations"]
                                if o["entity_id"] == entity_id
                            ),
                            default=-1,
                        )
                        if observed < last:
                            raise RuleError("Newer scenario observation already exists")
                        before = obj["status"]
                        obj["status"] = value
                        after = value
                    elif field == "container.release":
                        if type(value) is not bool:
                            raise RuleError("Release value must be true or false")
                        before = obj["released"]
                        obj.update(
                            released=value,
                            hold_reason=None if value else "Authority feed hold",
                        )
                        after = value
                    elif field == "container.position":
                        if (
                            not isinstance(value, dict)
                            or set(value) != {"location_id", "tier"}
                            or type(value["tier"]) is not int
                            or value["tier"] < 0
                        ):
                            raise RuleError(
                                "Position needs a location and nonnegative integer tier"
                            )
                        location = by_id(candidate["locations"], value["location_id"])
                        if not location or value["tier"] >= location["capacity"]:
                            raise RuleError("Unknown location or tier outside capacity")
                        if obj["job_id"]:
                            raise RuleError(
                                "Cargo is in transit; reconcile the active move before correcting position"
                            )
                        if observed < state.get("position_observed", {}).get(
                            entity_id, 0
                        ):
                            raise RuleError(
                                "A newer physical position is already observed"
                            )
                        origin = by_id(candidate["locations"], obj["location_id"])
                        others = [
                            c for c in candidate["containers"] if c["id"] != entity_id
                        ]
                        if (
                            origin
                            and origin["kind"] == "yard"
                            and any(
                                c["location_id"] == obj["location_id"]
                                and c["tier"] > obj["tier"]
                                for c in others
                            )
                        ):
                            raise RuleError(
                                "Buried cargo correction requires a reconciled stack snapshot"
                            )
                        if location["kind"] == "yard":
                            next_tier = (
                                max(
                                    (
                                        c["tier"]
                                        for c in others
                                        if c["location_id"] == location["id"]
                                    ),
                                    default=-1,
                                )
                                + 1
                            )
                            if value["tier"] != next_tier:
                                raise RuleError(
                                    "Corrected yard tier must be the next accessible top tier; gaps and collisions are refused"
                                )
                        before = {k: obj[k] for k in ("location_id", "tier")}
                        obj.update(value)
                        if candidate.get("movement"):
                            obj["custody"] = dict(
                                kind="location", id=value["location_id"]
                            )
                        after = value
                        candidate.setdefault("position_observed", {})[
                            entity_id
                        ] = observed
                    else:
                        raise RuleError("Unsupported observation kind")
                    validate(candidate)
                    candidate.setdefault("input_provenance", {})[key] = dict(
                        source=envelope["source"],
                        event_id=envelope["event_id"],
                        sequence=envelope["sequence"],
                        observed_minute=observed,
                        received_minute=receipt["receive_minute"],
                        known_revision=state["revision"] + 1,
                        value=after,
                        receipt_id=receipt["id"],
                    )
                    state.clear()
                    state.update(candidate)
                    outcome, reason = (
                        "applied",
                        "Validated authoritative observation applied to current state",
                    )
        except (RuleError, ValueError, TypeError, KeyError) as exc:
            outcome, reason = "quarantined", str(exc)
            after = None
        connection.execute(
            "UPDATE feed_receipts SET status=%s,reason=%s,entity_id=%s,field=%s,observed_minute=%s,applied_revision=%s,before_value=%s,after_value=%s,recorded_at=now() WHERE id=%s",
            (
                outcome,
                reason,
                entity_id,
                field,
                observed,
                state["revision"] + 1,
                Jsonb(before),
                Jsonb(after),
                receipt["id"],
            ),
        )
        events.append(
            dict(
                kind=f"input.{outcome}",
                entity_id=entity_id or envelope.get("external_id", "unknown"),
                valid_minute=observed if observed is not None else state["minute"],
                source=envelope.get("source", "input"),
                receipt_id=receipt["id"],
                message=reason,
            )
        )
    return events
