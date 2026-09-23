"""Read-only inspection of a saved approved schedule. No credentials printed."""

import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.store import Store, ROOT

p = argparse.ArgumentParser()
p.add_argument("--run", required=True)
p.add_argument("--equipment", default="YC-1")
args = p.parse_args()
s = Store()
with s.connect() as c:
    plan = c.execute(
        "SELECT id FROM schedule_plans WHERE run_id=%s AND approved_command IS NOT NULL ORDER BY created_at DESC LIMIT 1",
        (args.run,),
    ).fetchone()
    if not plan:
        raise SystemExit("Approve a schedule in this run first")
    params = {"run": args.run, "plan": plan["id"], "equipment": args.equipment}
    for name in ("schedule_feedback", "schedule_exposure"):
        sql = (ROOT / "sql" / f"{name}.sql").read_text()
        rows = c.execute(sql, params).fetchall()
        print(json.dumps({"query": name, "rows": rows}, indent=2, default=str))
        print(
            "\n".join(
                r["QUERY PLAN"]
                for r in c.execute(
                    "EXPLAIN (ANALYZE,BUFFERS) " + sql, params
                ).fetchall()
            )
        )
