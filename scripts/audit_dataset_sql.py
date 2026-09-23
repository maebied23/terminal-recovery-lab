"""Save a reproducible query plan for the actual input-impact query; no scale claim."""

import json
import uuid
from pathlib import Path
from app.store import Store
from app.datasets import load_pack, import_pack
from app.data_evidence import IMPACT_SQL

store = Store()
pack = load_pack("baseline-shift")
run = import_pack(store, "baseline-shift", str(uuid.uuid4()), pack["digest"])["id"]
with store.connect() as c:
    params = dict(run=run, entity="YC-1")
    result = c.execute(IMPACT_SQL, params).fetchall()
    plan = c.execute(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + IMPACT_SQL, params
    ).fetchone()["QUERY PLAN"]
out = Path(__file__).resolve().parents[1] / "docs/data-foundation"
out.mkdir(parents=True, exist_ok=True)
(out / "sql-query-plan.json").write_text(
    json.dumps(
        dict(
            run=run,
            rows=result,
            plan=plan,
            scope="One 144-container, 37-job local dataset. Query plan evidence, not an enterprise scale benchmark.",
        ),
        indent=2,
        default=str,
    )
    + "\n"
)
print(
    json.dumps(
        dict(run=run, commitments=len(result), execution_ms=plan[0]["Execution Time"])
    )
)
