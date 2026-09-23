"""Leased evaluation cases. Results never write to operational projections."""

import logging
import platform
import uuid
from psycopg.types.json import Jsonb
from .domain import RuleError
from .evaluation import manifest, scenario_state, evaluate_case, digest
from .store import ROOT

LOG = logging.getLogger("terminal.evaluation")


def enqueue(store, run, revision, suite, source_request=None):
    if suite not in ("development", "holdout", "case", "movement"):
        raise RuleError("Unknown evaluation suite")
    m = manifest()
    if suite == "movement":
        m["seeds"] = [101]
        m["sampling_note"] = (
            "One execution per family/strategy: stage durations are deterministic; repeated seeds would not be independent evidence."
        )

    m["runtime"] = dict(python=platform.python_version(), machine=platform.machine())
    import ortools

    m["runtime"]["ortools"] = ortools.__version__
    with store.connect() as c:
        m["schema_version"] = c.execute(
            "SELECT max(version) AS version FROM schema_version"
        ).fetchone()["version"]
        s = store.read(run, c, lock=True)
        if s["revision"] != revision or s["running"]:
            raise RuleError("Pause at the current revision before evaluation")
        if c.execute(
            "SELECT 1 FROM evaluation_runs WHERE run_id=%s AND status IN ('queued','running')",
            (run,),
        ).fetchone():
            raise RuleError("An evaluation is already queued or running")
        comparison = None
        if source_request:
            if suite != "case":
                raise RuleError(
                    "Saved comparisons are only used by the selected-case suite"
                )
            req = c.execute(
                "SELECT * FROM schedule_requests WHERE run_id=%s AND id=%s AND status='completed'",
                (run, source_request),
            ).fetchone()
            if not req:
                raise RuleError("Completed comparison not found in this run")
            s, comparison = req["snapshot"], req["result"]
        if suite == "case":
            specs = [
                dict(
                    id="selected-case",
                    title="Frozen selected-run case",
                    known={},
                    duration_factor=s["duration_factor"],
                    events=[],
                )
            ]
        else:
            specs = m[suite]
        m["case_count"], m["expected_trials"] = (
            len(specs),
            len(specs) * len(m["seeds"]) * 3,
        )
        m["basis"] = (
            "saved comparison"
            if source_request
            else (
                "selected run"
                if suite == "case"
                else "versioned fixtures; independent of selected operational run"
            )
        )
        eid = str(uuid.uuid4())
        c.execute(
            "INSERT INTO evaluation_runs(id,run_id,base_revision,source_request,suite,manifest) VALUES(%s,%s,%s,%s,%s,%s)",
            (eid, run, s["revision"], source_request, suite, Jsonb(m)),
        )
        for n, spec in enumerate(specs):
            state = s if suite == "case" else scenario_state(spec)
            c.execute(
                "INSERT INTO evaluation_cases(evaluation_id,case_id,ordinal,scenario,snapshot,comparison) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    eid,
                    spec["id"],
                    n,
                    Jsonb(spec),
                    Jsonb(state),
                    Jsonb(comparison) if comparison else None,
                ),
            )
    return eid


def work(store):
    with store.connect() as c:
        task = c.execute(
            """SELECT t.*,e.manifest FROM evaluation_cases t JOIN evaluation_runs e ON e.id=t.evaluation_id
          WHERE e.status IN ('queued','running') AND (t.status='queued' OR (t.status='running' AND t.lease_until<now()))
          ORDER BY e.created_at,t.ordinal FOR UPDATE OF t,e SKIP LOCKED LIMIT 1"""
        ).fetchone()
        if not task:
            return False
        eid, cid, attempt = task["evaluation_id"], task["case_id"], task["attempts"] + 1
        if attempt > 3:
            c.execute(
                "UPDATE evaluation_cases SET status='failed',error='Lease expired three times' WHERE evaluation_id=%s AND case_id=%s",
                (eid, cid),
            )
            c.execute(
                "UPDATE evaluation_runs SET status='failed',error='Case retry budget exhausted',completed_at=now() WHERE id=%s",
                (eid,),
            )
            return True
        c.execute("UPDATE evaluation_runs SET status='running' WHERE id=%s", (eid,))
        c.execute(
            "UPDATE evaluation_cases SET status='running',attempts=%s,lease_until=now()+interval '180 seconds' WHERE evaluation_id=%s AND case_id=%s",
            (attempt, eid, cid),
        )

    def heartbeat():
        with store.connect() as c:
            row = c.execute(
                """UPDATE evaluation_cases t SET lease_until=now()+interval '180 seconds'
              FROM evaluation_runs e WHERE t.evaluation_id=e.id AND e.id=%s AND t.case_id=%s
              AND e.status='running' AND t.status='running' AND t.attempts=%s RETURNING t.case_id""",
                (eid, cid, attempt),
            ).fetchone()
            if not row:
                raise RuleError("Evaluation cancelled or lease ownership changed")

    try:
        m = task["manifest"]
        if (
            m.get("provenance_version") == 2
            and m["planner_digest"] != manifest()["planner_digest"]
        ):
            raise RuleError(
                "Implementation changed after enqueue; create a new evaluation with current provenance"
            )
        result = evaluate_case(
            task["snapshot"],
            task["scenario"],
            m["seeds"],
            m["horizon"],
            m["solver_seconds"],
            task["comparison"],
            heartbeat,
        )
        with store.connect() as c:
            # Lock parent first, same order as cancellation, and recheck ownership.
            parent = c.execute(
                "SELECT status FROM evaluation_runs WHERE id=%s FOR UPDATE", (eid,)
            ).fetchone()
            owned = c.execute(
                "SELECT 1 FROM evaluation_cases WHERE evaluation_id=%s AND case_id=%s AND status='running' AND attempts=%s FOR UPDATE",
                (eid, cid, attempt),
            ).fetchone()
            if not parent or parent["status"] != "running" or not owned:
                return True
            for t in result["trials"]:
                c.execute(
                    "INSERT INTO evaluation_trials VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        eid,
                        cid,
                        t["seed"],
                        t["strategy"],
                        t["validation"],
                        t["execution_status"],
                        Jsonb(t["observed"]) if t["observed"] is not None else None,
                        Jsonb(t["predicted"]),
                        t["changed_bookings_vs_baseline"],
                        t.get("duration_stream_digest"),
                        Jsonb(t),
                    ),
                )
                for v in t["visits"]:
                    c.execute(
                        "INSERT INTO evaluation_visit_outcomes VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            eid,
                            cid,
                            t["seed"],
                            t["strategy"],
                            v["visit_id"],
                            v["container_id"],
                            v["commitment_id"],
                            v["cutoff"],
                            v["completion"],
                            v["on_time"],
                            v["lateness"],
                        ),
                    )
            c.execute(
                "UPDATE evaluation_cases SET status='completed',result=%s,comparison=%s,lease_until=NULL WHERE evaluation_id=%s AND case_id=%s",
                (
                    Jsonb(
                        {
                            k: v
                            for k, v in result.items()
                            if k not in ("trials", "comparison")
                        }
                    ),
                    Jsonb(result["comparison"]),
                    eid,
                    cid,
                ),
            )
            c.execute(
                "UPDATE evaluation_runs SET status='completed',completed_at=now() WHERE id=%s AND NOT EXISTS(SELECT 1 FROM evaluation_cases WHERE evaluation_id=%s AND status<>'completed')",
                (eid, eid),
            )
        LOG.info(
            "evaluation_case_completed evaluation=%s case=%s trials=%s seconds=%s",
            eid,
            cid,
            len(result["trials"]),
            result["elapsed_seconds"],
        )
    except Exception as exc:
        LOG.exception("evaluation_case_failed evaluation=%s case=%s", eid, cid)
        with store.connect() as c:
            # Cancellation and a newer worker take precedence over this old attempt.
            parent = c.execute(
                "SELECT status FROM evaluation_runs WHERE id=%s FOR UPDATE", (eid,)
            ).fetchone()
            if parent and parent["status"] == "running":
                owned = c.execute(
                    "UPDATE evaluation_cases SET status='failed',error=%s,lease_until=NULL WHERE evaluation_id=%s AND case_id=%s AND attempts=%s AND status='running' RETURNING case_id",
                    (
                        (
                            str(exc)
                            if isinstance(exc, RuleError)
                            else "Evaluation failed; inspect server logs"
                        ),
                        eid,
                        cid,
                        attempt,
                    ),
                ).fetchone()
                if owned:
                    c.execute(
                        "UPDATE evaluation_runs SET status='failed',error='A case failed; completed cases remain available',completed_at=now() WHERE id=%s",
                        (eid,),
                    )
    return True


def listing(store, run):
    with store.connect() as c:
        return c.execute(
            """SELECT e.id,e.base_revision,e.source_request,e.suite,e.status,e.error,e.created_at,e.completed_at,
        count(t.case_id) AS total_cases,count(*) FILTER(WHERE t.status='completed') AS completed_cases
        FROM evaluation_runs e LEFT JOIN evaluation_cases t ON t.evaluation_id=e.id WHERE e.run_id=%s
        GROUP BY e.id ORDER BY e.created_at DESC LIMIT 20""",
            (run,),
        ).fetchall()


def report(store, run, eid, export=False):
    with store.connect() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        e = c.execute(
            "SELECT * FROM evaluation_runs WHERE run_id=%s AND id=%s", (run, eid)
        ).fetchone()
        if not e:
            raise RuleError("Evaluation not found in this run")
        e["summary"] = c.execute(
            (ROOT / "sql/evaluation_summary.sql").read_text(), dict(evaluation=eid)
        ).fetchall()
        e["service_impact"] = c.execute(
            (ROOT / "sql/evaluation_service_impact.sql").read_text(),
            dict(evaluation=eid),
        ).fetchall()
        cases = c.execute(
            "SELECT * FROM evaluation_cases WHERE evaluation_id=%s ORDER BY ordinal",
            (eid,),
        ).fetchall()
        e["cases"] = (
            cases
            if export
            else [
                {k: v for k, v in x.items() if k not in ("snapshot", "comparison")}
                for x in cases
            ]
        )
        fields = (
            "*"
            if export
            else "case_id,seed,strategy,validation,execution_status,metrics,predicted,changed_bookings,stream_digest,details->>'interrupt_reason' AS interrupt_reason"
        )
        e["trials"] = c.execute(
            f"SELECT {fields} FROM evaluation_trials WHERE evaluation_id=%s ORDER BY case_id,seed,strategy",
            (eid,),
        ).fetchall()
        e["complete"] = e["status"] == "completed"
        return e


def cancel(store, run, eid):
    with store.connect() as c:
        row = c.execute(
            "UPDATE evaluation_runs SET status='cancelled',completed_at=now() WHERE run_id=%s AND id=%s AND status IN ('queued','running') RETURNING id",
            (run, eid),
        ).fetchone()
        if not row:
            raise RuleError("Evaluation is missing or no longer active")
    return dict(status="cancelled")
