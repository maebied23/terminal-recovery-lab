"""Equipment observations: durable receipt and reconciliation in one transaction.

Transport retries are at-least-once. Canonical source event identities suppress
repeated state effects. Browser commands and this scoped adapter remain separate.
"""

import logging
from psycopg.types.json import Jsonb
from .domain import RuleError
from .feed import reconcile_due
from .store import ROOT

LOG = logging.getLogger("terminal.integration")


def receive(store, run, envelope):
    with store.connect() as c:
        state = store.read(run, c, lock=True)
        if "dataset" not in state:
            raise RuleError("Import a dataset before connecting observations")
        ordinal = c.execute(
            "SELECT coalesce(max(ordinal),0)+1 AS n FROM feed_receipts WHERE run_id=%s",
            (run,),
        ).fetchone()["n"]
        receipt = c.execute(
            "INSERT INTO feed_receipts(run_id,ordinal,receive_minute,envelope,transport) VALUES(%s,%s,%s,%s,'equipment-adapter') RETURNING id",
            (run, ordinal, state["minute"], Jsonb(envelope)),
        ).fetchone()["id"]
        events = reconcile_due(c, run, state)
        if any(e["kind"] == "input.applied" for e in events) and state.get(
            "schedule", {}
        ).get("status") in ("approved", "executing"):
            from .schedule_execution import interrupt

            interrupt(
                state, events, "Accepted equipment input changed the planning basis"
            )
        # Any receipt is new knowledge, including a duplicate or quarantine. No clock step.
        state["revision"] += 1
        store.persist(c, run, state, events, None)
        result = c.execute(
            "SELECT id,status,reason,entity_id,applied_revision,received_at FROM feed_receipts WHERE id=%s",
            (receipt,),
        ).fetchone()
    LOG.info(
        "equipment_receipt run=%s receipt=%s revision=%s status=%s",
        run,
        receipt,
        state["revision"],
        result["status"],
    )
    return dict(result, durable=True, simulated=True)


def status(store, run):
    with store.connect() as c:
        store.read(
            run, c
        )  # Reject unknown run; do not infer equipment state from transport age.
        row = c.execute(
            (ROOT / "sql/integration_status.sql").read_text(), {"run": run}
        ).fetchone()
    return dict(
        row,
        simulated=True,
        note="Receipt freshness describes the sender, not whether equipment is available. Inspect input evidence for affected work.",
    )
