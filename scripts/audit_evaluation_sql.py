"""Small-fixture EXPLAIN evidence. No extrapolation to enterprise performance."""

import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.store import Store, ROOT

r = json.loads((ROOT / "docs/evaluation/holdout-report.json").read_text())
with Store().connect() as c:
    for name in ("evaluation_summary.sql", "evaluation_service_impact.sql"):
        query = (ROOT / "sql" / name).read_text()
        print(name)
        for row in c.execute(
            "EXPLAIN (ANALYZE, BUFFERS) " + query, dict(evaluation=r["id"])
        ):
            print(row["QUERY PLAN"])
