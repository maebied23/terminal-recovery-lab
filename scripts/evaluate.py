"""Run versioned suites locally; save reproducible reports without changing live work."""

import argparse, json, sys, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.store import Store, ROOT
from app.datasets import load_pack
from app.evaluation_store import enqueue, work, report

p = argparse.ArgumentParser()
p.add_argument("--suite", choices=["development", "holdout", "movement"], default="holdout")
p.add_argument("--run")
args = p.parse_args()
store = Store()
store.initialize()
run = args.run or "eval-" + str(uuid.uuid4())[:8]
if not args.run:
    with store.connect() as c:
        store.create_run(
            c, run, "Step 5 · evaluation review", load_pack("baseline-shift")["state"]
        )
eid = enqueue(store, run, store.read(run)["revision"], args.suite)
print(json.dumps(dict(run=run, evaluation=eid)), flush=True)
while True:
    r = report(store, run, eid, True)
    if r["status"] not in ("queued", "running"):
        break
    work(store)
    print(
        "Completed cases:",
        sum(c["status"] == "completed" for c in report(store, run, eid)["cases"]),
        flush=True,
    )
path = ROOT / "docs/evaluation" / f"{args.suite}-report.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(r, default=str, indent=2) + "\n")
print(r["status"], r["summary"], flush=True)
if r["status"] != "completed":
    raise SystemExit(1)
