"""Offline routing/citation benchmark. Never makes provider calls."""

import os, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("TERMINAL_ASSISTANT_PROVIDER", None)
from app.store import Store, ROOT
from app.assistant import assistant

store = Store()
if len(sys.argv) != 2:
    raise SystemExit("Usage: python scripts/evaluate_assistant.py RUN_ID")
run = sys.argv[1]
rows = []
for case in json.loads((ROOT / "evaluation/assistant-cases.json").read_text()):
    result = assistant(store, run, case["question"], case["selected"])
    first = result["calls"][0] if result["calls"] else None
    checks = dict(
        tool=(first["tool"] if first else None) == case["tool"],
        canonical_answer=result["answer"]
        == "\n\n".join(c["text"] for c in result["citations"]),
        citations=bool(result["citations"]),
        no_mutation=not result["mutation_allowed"],
    )
    if "argument" in case:
        checks["argument"] = (
            case["argument"] in (first or {}).get("arguments", {}).values()
        )
    if "contains" in case:
        checks["abstention"] = case["contains"] in result["answer"]
    rows.append(
        dict(
            question=case["question"],
            checks=checks,
            passed=all(checks.values()),
            elapsed_ms=result["elapsed_ms"],
            trace_id=result["trace_id"],
            usage=result["usage"],
        )
    )
report = dict(
    mode="offline evidence router; real OpenAI quality NOT measured",
    cases=len(rows),
    passed=sum(r["passed"] for r in rows),
    results=rows,
)
(ROOT / "docs/assistant").mkdir(parents=True, exist_ok=True)
(ROOT / "docs/assistant/offline-report.json").write_text(
    json.dumps(report, indent=2) + "\n"
)
print(json.dumps(report, indent=2))
if report["passed"] != report["cases"]:
    raise SystemExit(1)
