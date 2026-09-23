"""Revision-consistent input evidence, source rows and SQL-derived downstream exposure."""

from pathlib import Path
from .domain import RuleError

IMPACT_SQL = (Path(__file__).resolve().parents[1] / "sql/input_impact.sql").read_text()


def evidence(store, run, revision, entity):
    with store.connect() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        current = c.execute(
            "SELECT revision,minute FROM runs WHERE id=%s", (run,)
        ).fetchone()
        if not current:
            raise RuleError("Run not found")
        revision = current["revision"] if revision is None else revision
        snapshot = c.execute(
            "SELECT minute,state FROM snapshots WHERE run_id=%s AND revision=%s",
            (run, revision),
        ).fetchone()
        if not snapshot:
            raise RuleError("Snapshot not found")
        imported = c.execute(
            "SELECT * FROM dataset_imports WHERE run_id=%s", (run,)
        ).fetchone()
        if not imported:
            return dict(
                dataset=None, revision=revision, origin=snapshot["state"].get("dataset")
            )
        receipts = c.execute(
            "SELECT id,ordinal,envelope,status,reason,entity_id,field,observed_minute,receive_minute,applied_revision,before_value,after_value,recorded_at,delivery_lag_minutes FROM feed_evidence WHERE run_id=%s AND applied_revision<=%s ORDER BY receive_minute,ordinal LIMIT 200",
            (run, revision),
        ).fetchall()
        counts = c.execute(
            "SELECT count(*) FILTER(WHERE applied_revision<=%s AND status='applied')::int AS applied,count(*) FILTER(WHERE applied_revision<=%s AND status='quarantined')::int AS quarantined,count(*) FILTER(WHERE applied_revision<=%s AND status='duplicate')::int AS duplicates,count(*) FILTER(WHERE applied_revision<=%s AND status='stale')::int AS stale,count(*) FILTER(WHERE applied_revision IS NULL OR applied_revision>%s)::int AS awaiting_delivery FROM feed_receipts WHERE run_id=%s",
            (revision, revision, revision, revision, revision, run),
        ).fetchone()
        rows = c.execute(
            "SELECT file_name,row_number,raw FROM dataset_rows WHERE run_id=%s AND (raw->>'id'=%s OR raw->>'container_id'=%s OR raw->>'entity_id'=%s OR raw->>'equipment_id'=%s OR raw->>'job_id'=%s) ORDER BY file_name,row_number LIMIT 30",
            (run, entity, entity, entity, entity, entity),
        ).fetchall()
        windows = c.execute(
            "SELECT equipment_id,lower(availability_span) AS start_minute,upper(availability_span) AS end_minute,availability_span @> %s::integer AS permits_dispatch,source FROM equipment_windows WHERE run_id=%s AND equipment_id=%s ORDER BY lower(availability_span)",
            (snapshot["minute"], run, entity),
        ).fetchall()
        impact = (
            c.execute(IMPACT_SQL, dict(run=run, entity=entity)).fetchall()
            if revision == current["revision"]
            else None
        )
        return dict(
            dataset=imported,
            revision=revision,
            minute=snapshot["minute"],
            counts=counts,
            receipts=receipts,
            source_rows=rows,
            windows=windows,
            impact=impact,
            entity_id=entity,
            provenance={
                k: v
                for k, v in snapshot["state"].get("input_provenance", {}).items()
                if k.startswith(entity + "/")
            },
            impact_note=(
                "Active work linked through primary assignment, recorded resource use, or dependencies. Compatible fallback equipment is not a reservation; these counts do not predict missed departures."
                if impact is not None
                else "Downstream SQL exposure is current-state only. This historical view shows the original source rows and receipts known at its revision."
            ),
        )
