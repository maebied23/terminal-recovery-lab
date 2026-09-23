import { useEffect, useState } from "react";
import { serviceName } from "./departure";
import type { State } from "./types";

type Evaluation = {
  id: string;
  suite: string;
  status: string;
  total_cases: number;
  completed_cases: number;
  base_revision: number;
  error?: string;
};
type Report = Evaluation & {
  complete: boolean;
  source_request?: string;
  manifest: {
    basis: string;
    seeds: number[];
    expected_trials: number;
    limitations: string[];
  };
  summary: Array<{
    strategy: string;
    attempted: number;
    executed: number;
    paired: number;
    wins: number;
    ties: number;
    losses: number;
    interrupted: number;
    mean_on_time: number | null;
    mean_delta: number | null;
    p10_on_time: number | null;
    p90_on_time: number | null;
    mean_prediction_error: number | null;
    mean_changed_bookings: number | null;
  }>;
  cases: Array<{
    case_id: string;
    status: string;
    error?: string;
    scenario: { title: string };
  }>;
  service_impact: Array<{
    strategy: string;
    commitment_id: string;
    samples: number;
    mean_on_time: number;
    cargo_per_case: number;
    harmed_samples: number;
    mean_delta: number;
  }>;
  trials: Array<{
    case_id: string;
    seed: number;
    strategy: string;
    validation: string;
    execution_status: string;
    metrics: { on_time: number; prediction_error: number } | null;
    interrupt_reason?: string;
  }>;
};
const label = (s: string) =>
  ({
    baseline: "Keep assignments",
    deadline: "Earliest deadline",
    constraint: "Constraint scheduler",
  })[s] || s;
export function EvaluationPanel({
  run,
  s,
  api,
  readOnly = false,
  onReportSelect,
}: {
  run: string;
  s: State;
  api: (url: string, body?: unknown) => Promise<any>;
  readOnly?: boolean;
  onReportSelect?: (id: string) => void;
}) {
  const [items, setItems] = useState<Evaluation[]>([]),
    [id, setId] = useState(""),
    [report, setReport] = useState<Report | null>(null),
    [suite, setSuite] = useState("holdout"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [caseId, setCaseId] = useState(""),
    [source, setSource] = useState("");
  const [comparisons, setComparisons] = useState<
    Array<{ id: string; base_revision: number; status: string }>
  >([]);
  useEffect(() => {
    let live = true;
    const refresh = async () => {
      try {
        const [rows, plans] = await Promise.all([
          api(`/api/evaluations?run=${encodeURIComponent(run)}`),
          api(`/api/schedules?run=${encodeURIComponent(run)}`),
        ]);
        if (live) {
          setItems(rows);
          setComparisons(
            plans.filter((p: { status: string }) => p.status === "completed"),
          );
          setError("");
        }
      } catch (e) {
        if (live) setError(String(e));
      }
    };
    refresh();
    const t = setInterval(refresh, 4000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [run, api]);
  useEffect(() => {
    setId("");
    setReport(null);
    setSource("");
  }, [run]);
  const chosen = id || items[0]?.id;
  useEffect(() => {
    onReportSelect?.(chosen || "");
  }, [chosen, onReportSelect]);
  useEffect(() => {
    if (!chosen) {
      setReport(null);
      return;
    }
    let live = true;
    setReport(null);
    setCaseId("");
    const refresh = () =>
      api(`/api/evaluations/${chosen}?run=${encodeURIComponent(run)}`)
        .then((r) => {
          if (live) setReport(r);
        })
        .catch((e) => {
          if (live) setError(String(e));
        });
    refresh();
    const t = setInterval(refresh, 4000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [chosen, run, api]);
  const active = items.some((r) => ["queued", "running"].includes(r.status));
  async function start() {
    setBusy(true);
    setError("");
    try {
      const r = await api(`/api/evaluations?run=${encodeURIComponent(run)}`, {
        suite,
        expected_revision: s.revision,
        source_request: suite === "case" && source ? source : null,
      });
      setId(r.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const detail = caseId || report?.cases[0]?.case_id;
  return (
    <section className="panel evaluation-panel">
      <div className="eyebrow">MEASURE BEFORE TRUSTING</div>
      <h2>Does the plan survive execution?</h2>
      <p>
        Compare the same work and execution seeds across three scheduling
        strategies. Plans are frozen before future disruptions are revealed.
        These tests never dispatch work in your live shift.
      </p>
      <div className="evaluation-controls">
        <label>
          Test family
          <select
            aria-label="Evaluation suite"
            value={suite}
            onChange={(e) => setSuite(e.target.value)}
          >
            <option value="holdout">
              New stress families · 6 cases / 54 trials
            </option>
            <option value="development">
              Reference cases · 3 cases / 27 trials
            </option>
            <option value="case">
              This run or a saved comparison · 9 trials
            </option>
          </select>
        </label>
        {suite === "case" && (
          <label>
            Decision basis
            <select
              aria-label="Evaluation basis"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            >
              <option value="">Current paused revision {s.revision}</option>
              {comparisons.map((p) => (
                <option key={p.id} value={p.id}>
                  Saved comparison at revision {p.base_revision} ·{" "}
                  {p.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          className="primary"
          onClick={start}
          disabled={readOnly || s.running || active || busy}
        >
          {busy ? "Queuing…" : "Run evaluation"}
        </button>
      </div>
      <p className="micro">
        Pause first. Tests run in the background and may take several minutes on
        this laptop. New stress families become regression cases once reviewed;
        they are not real-terminal validation.
      </p>
      {error && <p role="alert">{error}</p>}
      {items.length > 0 && (
        <label>
          Saved report
          <select
            aria-label="Evaluation report"
            value={chosen || ""}
            onChange={(e) => setId(e.target.value)}
          >
            {items.map((r) => (
              <option value={r.id} key={r.id}>
                {r.suite} · {r.status} · {r.completed_cases}/{r.total_cases}{" "}
                cases · {r.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
      )}
      {report && (
        <>
          <div className="notice">
            <b>
              {report.status} ·{" "}
              {report.cases.filter((c) => c.status === "completed").length}/
              {report.cases.length} cases
            </b>{" "}
            · {report.manifest.basis}.{" "}
            {report.source_request &&
              `Saved plan basis: revision ${report.base_revision}. `}
            {!report.complete &&
              "Partial results: do not interpret these as the complete suite."}
            {report.error}
          </div>
          <div className="evaluation-controls">
            <a
              href={`/api/evaluations/${report.id}?run=${encodeURIComponent(run)}&export=true`}
              target="_blank"
              rel="noreferrer"
            >
              Open reproducible JSON report
            </a>
            {["queued", "running"].includes(report.status) && (
              <button
                onClick={async () => {
                  try {
                    await api(
                      `/api/evaluations/${report.id}/cancel?run=${encodeURIComponent(run)}`,
                      {},
                    );
                    setReport(
                      await api(
                        `/api/evaluations/${report.id}?run=${encodeURIComponent(run)}`,
                      ),
                    );
                  } catch (e) {
                    setError(String(e));
                  }
                }}
              >
                Cancel remaining tests
              </button>
            )}
          </div>
          <div className="evaluation-cards">
            {report.summary.map((r) => (
              <article key={r.strategy}>
                <h3>{label(r.strategy)}</h3>
                <strong>{r.mean_on_time ?? "—"} cargo on time</strong>
                <p>
                  Mean across {r.executed}/{r.attempted} recorded executions
                </p>
                <p>
                  {r.wins} wins · {r.ties} ties · {r.losses} losses
                  <br />
                  against keep assignments ({r.paired} paired trials)
                </p>
                <p>
                  Mean change: {r.mean_delta ?? "—"} cargo
                  <br />
                  P10–P90: {r.p10_on_time ?? "—"}–{r.p90_on_time ?? "—"} cargo
                  <br />
                  {r.interrupted} interrupted schedules
                </p>
                <small>
                  Projected minus actual: {r.mean_prediction_error ?? "—"}{" "}
                  cargo. Mean changed bookings: {r.mean_changed_bookings ?? "—"}
                  .
                </small>
              </article>
            ))}
          </div>
          <p className="micro">
            “Completed schedule” only means its booked work finished.
            Unscheduled cargo can still miss its departure. P10–P90 describes
            these synthetic samples, not calibrated confidence. No automatic
            replanning occurs after interruption.
          </p>
          <details>
            <summary>Which departures gained or lost?</summary>
            <div className="evaluation-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Departure</th>
                    <th>Strategy</th>
                    <th>Samples</th>
                    <th>Mean on time / cargo</th>
                    <th>Mean vs baseline</th>
                    <th>Harmed samples</th>
                  </tr>
                </thead>
                <tbody>
                  {report.service_impact.map((r) => (
                    <tr key={r.commitment_id + r.strategy}>
                      <td>{serviceName(r.commitment_id)}</td>
                      <td>{label(r.strategy)}</td>
                      <td>{r.samples}</td>
                      <td>
                        {r.mean_on_time} / {r.cargo_per_case}
                      </td>
                      <td>{r.mean_delta ?? "—"}</td>
                      <td>{r.harmed_samples}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <label>
            Inspect a case
            <select
              aria-label="Evaluation case"
              value={detail || ""}
              onChange={(e) => setCaseId(e.target.value)}
            >
              {report.cases.map((c) => (
                <option key={c.case_id} value={c.case_id}>
                  {c.scenario.title} · {c.status}
                </option>
              ))}
            </select>
          </label>
          {report.cases.find((c) => c.case_id === detail)?.error && (
            <p role="alert">
              {report.cases.find((c) => c.case_id === detail)?.error}
            </p>
          )}
          <div className="evaluation-scroll">
            <table>
              <thead>
                <tr>
                  <th>Seed</th>
                  <th>Strategy</th>
                  <th>Actual on time</th>
                  <th>Execution / interruption reason</th>
                </tr>
              </thead>
              <tbody>
                {report.trials
                  .filter((t) => t.case_id === detail)
                  .map((t) => (
                    <tr key={t.seed + t.strategy}>
                      <td>{t.seed}</td>
                      <td>{label(t.strategy)}</td>
                      <td>{t.metrics?.on_time ?? "Not executable"}</td>
                      <td>
                        {t.execution_status}
                        {t.interrupt_reason && ` · ${t.interrupt_reason}`}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary>Assumptions and limits</summary>
            <ul>
              {report.manifest.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </details>
        </>
      )}
    </section>
  );
}
