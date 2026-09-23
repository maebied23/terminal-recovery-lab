"""Bounded policy search with paired scenario seeds and a PostgreSQL lease."""

import uuid, time, logging, math, hashlib
from pathlib import Path
from statistics import mean
from psycopg.types.json import Jsonb
from .domain import simulate, apply_policy, deepcopy, blockers

POLICIES = {
    "fifo": "Current assignments",
    "rail-first": "Protect rail departures",
    "deadline": "Balance nearest deadlines",
    "vessel-first": "Protect vessel service",
}
LOG = logging.getLogger("terminal.planning")


def enqueue_experiment(store, run, seeds=5, horizon=180, purpose="compare"):
    with store.connect() as c:
        s = store.read(run, c, lock=True)
        id = str(uuid.uuid4())
        manifest = dict(
            schema_version=1,
            domain_sha256=hashlib.sha256(
                Path(__file__).with_name("domain.py").read_bytes()
            ).hexdigest(),
            seeds=[s["seed"] + i * 7919 for i in range(seeds)],
            horizon=horizon,
            policies=list(POLICIES),
            purpose=purpose,
            method="paired per-job deterministic duration sampling",
            noise="uniform ±20% of synthetic base duration; 1 minute transfer",
            calibration="not calibrated to a real terminal",
            base_revision=s["revision"],
            original_seed=s["seed"],
            input_dataset=s.get("dataset"),
            future_inputs="Undelivered replay observations are excluded. Forecast uses currently known state and published availability only.",
        )
        c.execute(
            "INSERT INTO experiments(id,run_id,base_revision,snapshot,manifest) VALUES(%s,%s,%s,%s,%s)",
            (id, run, s["revision"], Jsonb(s), Jsonb(manifest)),
        )
    return id


def percentile(values, p):
    vals = sorted(values)
    return vals[min(len(vals) - 1, max(0, math.ceil(p * len(vals)) - 1))]


def work_experiment(store):
    with store.connect() as c:
        # Expired leases are recoverable after a process crash; partial results are never published.
        row = c.execute(
            "SELECT * FROM experiments WHERE status='queued' OR (status='running' AND lease_until<now()) ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
        ).fetchone()
        if not row:
            return False
        if row["attempts"] >= 3:
            c.execute(
                "UPDATE experiments SET status='failed',error='Retry budget exhausted' WHERE id=%s",
                (row["id"],),
            )
            return True
        c.execute(
            "UPDATE experiments SET status='running',attempts=attempts+1,lease_until=now()+interval '90 seconds' WHERE id=%s",
            (row["id"],),
        )
    try:
        results = []
        start = time.perf_counter()
        total = len(POLICIES) * len(row["manifest"]["seeds"])
        done = 0
        for policy, title in POLICIES.items():
            runs = []
            for seed in row["manifest"]["seeds"]:
                with store.connect() as c:
                    if (
                        c.execute(
                            "SELECT status FROM experiments WHERE id=%s", (row["id"],)
                        ).fetchone()["status"]
                        == "cancelled"
                    ):
                        return True
                # The baseline reproduces the currently selected policy, not an unrelated FIFO run.
                effective = row["snapshot"]["policy"] if policy == "fifo" else policy
                r = simulate(
                    row["snapshot"],
                    effective,
                    seed,
                    row["manifest"]["horizon"],
                    reassign=policy != "fifo",
                )
                runs.append(r)
                done += 1
                with store.connect() as c:
                    c.execute(
                        "UPDATE experiments SET progress=%s,lease_until=now()+interval '90 seconds' WHERE id=%s AND status='running'",
                        (round(done / total * 100), row["id"]),
                    )
            metrics = [r["metrics"] for r in runs]
            projected = deepcopy(row["snapshot"])
            if policy != "fifo":
                apply_policy(projected, effective)
            changes = [
                dict(
                    job_id=j["id"],
                    container_id=j["container_id"],
                    commitment_id=next(
                        c["commitment_id"]
                        for c in projected["containers"]
                        if c["id"] == j["container_id"]
                    ),
                    before=old["equipment_id"],
                    after=j["equipment_id"],
                )
                for j, old in zip(projected["jobs"], row["snapshot"]["jobs"])
                if j["equipment_id"] != old["equipment_id"]
            ]
            candidate = dict(
                policy=policy,
                title=title,
                metrics={k: round(mean(m[k] for m in metrics), 2) for k in metrics[0]},
                interval=[
                    percentile([m["on_time"] for m in metrics], 0.1),
                    percentile([m["on_time"] for m in metrics], 0.9),
                ],
                curve=runs[0]["curve"],
                replications=[r["metrics"] for r in runs],
                changes=changes,
                unresolved=[
                    dict(job_id=j["id"], reasons=blockers(projected, j, True))
                    for j in projected["jobs"]
                    if j["status"] != "completed" and blockers(projected, j, True)
                ],
                explanation="Reassign only queued moves within crane reach; keep holds, precedence and capacity checks at dispatch.",
            )
            results.append(candidate)
        baseline = results[0]
        for result in results:
            result["delta_on_time"] = round(
                result["metrics"]["on_time"] - baseline["metrics"]["on_time"], 2
            )
        outcome = dict(
            candidates=results,
            elapsed_seconds=round(time.perf_counter() - start, 2),
            warning="Simulation ranges describe assumed variation, not real-world confidence or a guarantee.",
            recommended=min(
                results,
                key=lambda r: (r["metrics"]["missed"], r["metrics"]["lateness"]),
            )["policy"],
        )
        with store.connect() as c:
            rowlock = c.execute(
                "SELECT status FROM experiments WHERE id=%s FOR UPDATE", (row["id"],)
            ).fetchone()
            if rowlock["status"] == "cancelled":
                return True
            for result in results[1:]:
                pid = str(uuid.uuid4())
                result["plan_id"] = pid
                c.execute(
                    "INSERT INTO plans(id,run_id,base_revision,policy,evidence) VALUES(%s,%s,%s,%s,%s)",
                    (
                        pid,
                        row["run_id"],
                        row["base_revision"],
                        result["policy"],
                        Jsonb(
                            dict(
                                experiment_id=row["id"],
                                candidate=result,
                                manifest=row["manifest"],
                            )
                        ),
                    ),
                )
            c.execute(
                "UPDATE experiments SET status='completed',progress=100,result=%s WHERE id=%s",
                (Jsonb(outcome), row["id"]),
            )
        LOG.info(
            "experiment_completed id=%s seconds=%s",
            row["id"],
            outcome["elapsed_seconds"],
        )
    except Exception as exc:
        LOG.exception("experiment_failed id=%s", row["id"])
        with store.connect() as c:
            c.execute(
                "UPDATE experiments SET status='failed',error=%s WHERE id=%s",
                (type(exc).__name__, row["id"]),
            )
    return True
