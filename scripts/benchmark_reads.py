"""Bounded read workload, explicit database size and concurrency; not a load certification."""

import argparse, json, time, platform, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.store import Store, ROOT

p = argparse.ArgumentParser()
p.add_argument("--run", required=True)
p.add_argument("--requests", type=int, default=30)
p.add_argument("--concurrency", type=int, default=1)
args = p.parse_args()
if not 1 <= args.requests <= 1000 or not 1 <= args.concurrency <= 8:
    raise SystemExit("Bound: 1–1000 requests, 1–8 readers")
s = Store()


def read(_):
    start = time.perf_counter()
    s.read(args.run)
    return (time.perf_counter() - start) * 1000


with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
    latencies = sorted(pool.map(read, range(args.requests)))
with s.connect() as c:
    counts = {
        t: c.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
        for t in ["runs", "containers", "move_jobs", "snapshots", "events"]
    }
    plan = c.execute(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
        + (ROOT / "sql/integration_status.sql").read_text(),
        {"run": args.run},
    ).fetchone()["QUERY PLAN"]
print(
    json.dumps(
        dict(
            scope="Small local SQL-backed state reads, not planner or enterprise throughput",
            machine=platform.machine(),
            platform=platform.platform(),
            requests=args.requests,
            concurrency=args.concurrency,
            rows=counts,
            p50_ms=latencies[len(latencies) // 2],
            p95_ms=latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
            max_ms=max(latencies),
            query_plan=plan,
        ),
        indent=2,
        default=str,
    )
)
