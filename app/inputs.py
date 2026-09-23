"""Read-only external-feed rehearsal: raw ledger, identity validation, no live writes."""

from psycopg.types.json import Jsonb
from .domain import RuleError


def record(store, run, payload):
    with store.connect() as c:
        s = store.read(run, c, lock=True)
        old = c.execute(
            "SELECT * FROM input_events WHERE run_id=%s AND source=%s AND source_event_id=%s",
            (run, payload["source"], payload["source_event_id"]),
        ).fetchone()
        if old:
            if old["payload"] != payload:
                raise RuleError("Source event ID reused with conflicting content")
            return old
        reason = None
        if payload["entity_id"] not in {e["id"] for e in s["equipment"]}:
            reason = "Unknown equipment identity; explicit source mapping required"
        elif payload["event_time"] > s["minute"]:
            reason = "Event is ahead of the selected shift clock"
        c.execute(
            "INSERT INTO input_events(run_id,source,source_event_id,event_time,payload,status,reason) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                run,
                payload["source"],
                payload["source_event_id"],
                payload["event_time"],
                Jsonb(payload),
                "quarantined" if reason else "accepted",
                reason,
            ),
        )
        return c.execute(
            "SELECT * FROM input_events WHERE run_id=%s AND source=%s AND source_event_id=%s",
            (run, payload["source"], payload["source_event_id"]),
        ).fetchone()
