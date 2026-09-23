"""Capture plans for the actual diagnostic queries; these are local measurements."""

import json
import uuid
from pathlib import Path
from psycopg.types.json import Jsonb
from app.store import Store
from app.datasets import load_pack, import_pack
from app.diagnosis import diagnose, DEPENDENCIES, SUMMARY, CALENDAR

store = Store()
p = load_pack("baseline-shift")
run = import_pack(store, "baseline-shift", str(uuid.uuid4()), p["digest"])["id"]
state = store.read(run)
report = diagnose(store, run)
params = dict(
    run=run, current=True, state=Jsonb(state), minute=0, rows=Jsonb(report["manifest"])
)
plans = {}
with store.connect() as c:
    c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    for name, query in [
        ("diagnosis_dependencies.sql", DEPENDENCIES),
        ("diagnosis_summary.sql", SUMMARY),
        ("diagnosis_calendar.sql", CALENDAR),
    ]:
        plans[name] = c.execute(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, params
        ).fetchone()["QUERY PLAN"]
result = dict(
    run=run,
    scope="144 containers, 37 moves, 24 committed visits. Local query-plan evidence, not an enterprise benchmark.",
    plans=plans,
)
Path("docs/diagnosis").mkdir(parents=True, exist_ok=True)
Path("docs/diagnosis/sql-query-plans.json").write_text(
    json.dumps(result, indent=2, default=str) + "\n"
)
print(
    json.dumps(
        dict(
            run=run, execution_ms={k: v[0]["Execution Time"] for k, v in plans.items()}
        )
    )
)
