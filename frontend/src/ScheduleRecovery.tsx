import { useEffect, useState, useRef } from "react";
import type { State } from "./types";
import { clock } from "./types";
import { CaseMap } from "./CaseMap";
import { bookingChanges, reservationLabel } from "./booking";
import {
  cargoName,
  serviceName,
  equipmentName,
  placeName,
  readable,
} from "./departure";
import "./scheduling.css";

type Booking = {
  job_id: string;
  container_id: string;
  source_id: string;
  target_id: string;
  start: number;
  end: number;
  resources: string[];
  frozen: boolean;
  stages: import("./types").MovementStage[];
};
type Service = {
  id: string;
  total: number;
  on_time: number;
  unscheduled: number;
  lateness: number;
  cutoff: number;
};
type Candidate = {
  key: string;
  title: string;
  plan_id?: string;
  validation: string;
  error?: string;
  rows: Booking[];
  metrics?: {
    missed: number;
    lateness: number;
    rehandles: number;
    travel: number;
    changes: number;
  };
  services?: Service[];
  impact?: {
    id: string;
    on_time: number;
    total: number;
    delta: number | null;
  }[];
  unresolved?: { job_id: string; container_id: string; reasons: string[] }[];
};
type Comparison = {
  id: string;
  status: string;
  base_revision: number;
  focus_commitment: string;
  error?: string;
  result?: {
    base_minute: number;
    end_minute: number;
    recommended: string | null;
    assumptions: string[];
    solver: {
      reason?: string;
      status: string;
      engine: string;
      elapsed_seconds: number;
      scope: string;
      passes: {
        objective: string;
        status: string;
        value: number | null;
        bound: number;
      }[];
    };
    candidates: Candidate[];
  };
};
export type ApprovedSchedule = {
  id: string;
  status: string;
  title: string;
  reason?: string;
  rows: Booking[];
  projection: Service[];
  base_revision: number;
  end_minute: number;
};
type Feedback = {
  observed_revision: number;
  plan_id: string;
  job_id: string;
  container_id: string;
  planned_start: number;
  planned_end: number;
  actual_start: number | null;
  actual_end: number | null;
  execution_status: string;
  completion_variance: number | null;
};
type Props = {
  s: State;
  run: string;
  departure: string;
  request: (path: string, body?: unknown) => Promise<any>;
  command: (cmd: Record<string, unknown>) => void;
  select: (id: string) => void;
  caseJobs?: string[];
  selectedJob?: string;
};

export function ScheduleRecovery({
  s,
  run,
  departure,
  request,
  command,
  select,
  caseJobs,
  selectedJob,
}: Props) {
  const requestEpoch = useRef(0);
  const [showAllWork, setShowAllWork] = useState(false);
  const [fullHorizon, setFullHorizon] = useState(false);
  const [comparisons, setComparisons] = useState<Comparison[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [selected, setSelected] = useState(""),
    [confirm, setConfirm] = useState<Candidate | null>(null),
    [feedback, setFeedback] = useState<Feedback[]>([]);
  useEffect(() => {
    let live = true;
    requestEpoch.current++;
    async function refresh() {
      try {
        const [cs, fb] = await Promise.all([
          request(`/api/schedules?run=${encodeURIComponent(run)}`),
          request(`/api/schedules/feedback?run=${encodeURIComponent(run)}`),
        ]);
        if (live) {
          setComparisons(cs);
          setFeedback(fb);
        }
      } catch (e) {
        if (live) setError(String(e));
      }
    }
    setSelected("");
    setBusy(false);
    setComparisons([]);
    setFeedback([]);
    setConfirm(null);
    setError("");
    refresh();
    const timer = setInterval(refresh, 2500);
    return () => {
      live = false;
      requestEpoch.current++;
      clearInterval(timer);
    };
  }, [run, request]);
  const latest = comparisons.find((c) => c.status === "completed");
  const pending = comparisons.find((c) =>
    ["queued", "running"].includes(c.status),
  );
  const result = latest?.result;
  const candidate =
    result?.candidates.find((c) => c.key === selected) ||
    result?.candidates.find((c) => c.key === result.recommended) ||
    result?.candidates[0];
  const stale = !!latest && latest.base_revision !== s.revision;
  const plan = s.schedule;
  const changes = bookingChanges(
    result?.candidates.find((c) => c.key === "baseline")?.rows || [],
    candidate?.rows || [],
  );
  const changedIds = new Set(
    changes.filter((c) => c.changes.length).map((c) => c.job_id),
  );
  const caseRows =
    candidate?.rows.filter((r) => caseJobs?.includes(r.job_id)) || [];
  const focusEnd = caseRows.length
    ? Math.min(
        result?.end_minute || 180,
        Math.max(
          s.commitments.find((c) => c.id === departure)?.cutoff || 0,
          ...caseRows.map((r) => r.end),
        ) + 10,
      )
    : result?.end_minute || 180;
  const visibleRows =
    candidate?.rows.filter(
      (r) =>
        showAllWork ||
        candidate.key === "baseline" ||
        changedIds.has(r.job_id) ||
        caseJobs?.includes(r.job_id),
    ) || [];

  const build = async () => {
    const epoch = requestEpoch.current;
    setBusy(true);
    setError("");
    try {
      await request(`/api/schedules?run=${encodeURIComponent(run)}`, {
        expected_revision: s.revision,
        focus_commitment: departure,
        horizon: 180,
      });
      const rows = await request(
        `/api/schedules?run=${encodeURIComponent(run)}`,
      );
      if (epoch === requestEpoch.current) setComparisons(rows);
    } catch (e) {
      if (epoch === requestEpoch.current) setError(String(e));
    } finally {
      if (epoch === requestEpoch.current) setBusy(false);
    }
  };
  return (
    <section
      className="schedule-workspace"
      aria-label="Executable recovery planning"
    >
      <div className="panel schedule-intro">
        <div className="section-heading">
          <div>
            <div className="eyebrow">RECOVERY</div>
            <h2>Compare & book</h2>
          </div>
          <button
            className="primary"
            disabled={s.running || busy || !!pending}
            onClick={build}
          >
            {pending ? "Building schedules…" : "Build recovery schedules"}
          </button>
        </div>
        <p className="micro">
          {serviceName(departure)} · all terminal work competes. Approval books
          equipment; cargo moves during execution.
        </p>
        {s.running && (
          <p role="status">
            Pause the terminal clock before building or approving a schedule.
          </p>
        )}
        {error && <p role="alert">{error}</p>}
        {comparisons[0]?.status === "failed" && (
          <p role="alert">{comparisons[0].error}</p>
        )}
        {pending && (
          <p role="status">
            {pending.status === "queued"
              ? "Waiting for planner"
              : "Checking assignments, windows, precedence and physical replay"}{" "}
            · basis r{pending.base_revision}. You can keep inspecting the
            terminal.
          </p>
        )}
      </div>
      {plan && (
        <section className="panel approved-schedule">
          <div className="section-heading">
            <h3>Approved work · {plan.title}</h3>
            <strong>{plan.status}</strong>
          </div>
          <p>
            {plan.reason
              ? readable(s, plan.reason)
              : "Reserved work and its actual execution share the same state across Operations, Work and Evidence."}
          </p>
          <p>
            {
              plan.rows.filter(
                (r) =>
                  s.jobs.find((j) => j.id === r.job_id)?.status === "completed",
              ).length
            }{" "}
            / {plan.rows.length} booked moves completed · simulator
            acknowledgment is separate from completion.
          </p>
          <div className="schedule-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Departure</th>
                  <th>On time at approval (projection)</th>
                  <th>Actually delivered on time</th>
                  <th>Awaiting delivery</th>
                </tr>
              </thead>
              <tbody>
                {plan.projection.map((co) => {
                  const cargo = s.containers.filter(
                    (c) => c.commitment_id === co.id,
                  );
                  const destination = s.commitments.find(
                    (c) => c.id === co.id,
                  )?.location_id;
                  const delivered = cargo
                    .map((c) =>
                      s.jobs.filter(
                        (j) =>
                          j.container_id === c.id &&
                          j.target_id === destination &&
                          j.kind !== "rehandle",
                      ),
                    )
                    .filter((js) => js.length === 1)
                    .map((js) => js[0]);
                  return (
                    <tr key={co.id}>
                      <td>{serviceName(co.id)}</td>
                      <td>
                        {co.on_time}/{co.total}
                      </td>
                      <td>
                        {
                          delivered.filter(
                            (j) =>
                              j.status === "completed" &&
                              j.completed_at !== null &&
                              j.completed_at <= co.cutoff,
                          ).length
                        }
                        /{co.total}
                      </td>
                      <td>
                        {co.total -
                          delivered.filter((j) => j.status === "completed")
                            .length}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="schedule-actions">
            {["approved", "executing"].includes(plan.status) && (
              <button
                className="secondary"
                disabled={s.running}
                onClick={() => command({ action: "withdraw_schedule" })}
              >
                Withdraw future bookings
              </button>
            )}
            {["interrupted", "withdrawn", "completed"].includes(
              plan.status,
            ) && (
              <button
                className="secondary"
                disabled={s.running}
                onClick={() => command({ action: "resume_dispatch" })}
              >
                Return to automatic dispatch
              </button>
            )}
          </div>
          <details>
            <summary>Projected versus observed move completions</summary>
            <p className="micro">
              Move timing observed at revision{" "}
              {feedback.find((f) => f.plan_id === plan.id)?.observed_revision ??
                "loading"}
              ; terminal view r{s.revision}. These refresh independently from
              the same committed database.
            </p>
            <div className="schedule-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Cargo / work</th>
                    <th>Booked interval</th>
                    <th>Actual start → finish</th>
                    <th>Execution</th>
                  </tr>
                </thead>
                <tbody>
                  {feedback
                    .filter((f) => f.plan_id === plan.id)
                    .map((f) => (
                      <tr key={f.job_id}>
                        <td>
                          <button
                            className="text-button"
                            onClick={() => select(f.job_id)}
                          >
                            {cargoName(f.container_id)} · {f.job_id}
                          </button>
                        </td>
                        <td>
                          {clock(f.planned_start)}–{clock(f.planned_end)}
                        </td>
                        <td>
                          {f.actual_start === null
                            ? "—"
                            : clock(f.actual_start)}{" "}
                          →{" "}
                          {f.actual_end === null
                            ? "not completed"
                            : clock(f.actual_end)}
                        </td>
                        <td>{f.execution_status}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>
      )}
      {result && (
        <>
          <div className="section-heading">
            <h3>Departure outcomes</h3>
            <span>
              Basis r{latest!.base_revision} · {clock(result.base_minute)}–
              {clock(result.end_minute)}
            </span>
          </div>
          {stale && (
            <p className="notice warning" role="status">
              State changed. This comparison is evidence only; build new
              schedules before approval.
            </p>
          )}
          <div className="schedule-candidates">
            {result.candidates.map((c) => (
              <button
                className={`schedule-choice ${candidate?.key === c.key ? "chosen" : ""}`}
                key={c.key}
                onClick={() => setSelected(c.key)}
                aria-pressed={candidate?.key === c.key}
              >
                <small>
                  {c.key === "baseline"
                    ? "BASELINE"
                    : c.key === result.recommended
                      ? "BEST VALIDATED TRADEOFF"
                      : "ALTERNATIVE"}
                </small>
                <h3>{c.title}</h3>
                {c.metrics ? (
                  <>
                    <strong>
                      {c.services!.reduce((n, x) => n + x.on_time, 0)} /{" "}
                      {c.services!.reduce((n, x) => n + x.total, 0)} cargo on
                      time
                    </strong>
                    <p>
                      {c.metrics.missed} not protected · {c.metrics.rehandles}{" "}
                      relocations · {c.metrics.changes} changed assignments
                    </p>
                    <p className="micro">
                      {c.metrics.lateness} cargo-minutes beyond cutoff within
                      the horizon · {c.metrics.travel} modeled travel minutes
                    </p>
                    <span>Independent physical replay passed</span>
                  </>
                ) : (
                  <p>
                    {c.key === "constraint" && result.solver.reason
                      ? `Rejected by replay: ${readable(s, result.solver.reason)}`
                      : `${c.validation}: ${c.error}`}
                  </p>
                )}
              </button>
            ))}
          </div>
          {candidate?.validation === "passed" && (
            <section className="panel schedule-detail">
              <div className="section-heading">
                <h3>{candidate.title}</h3>
                <button
                  className="primary"
                  disabled={
                    stale ||
                    s.running ||
                    !candidate.plan_id ||
                    plan?.id === candidate.plan_id
                  }
                  onClick={() => setConfirm(candidate)}
                >
                  Review schedule for approval
                </button>
              </div>
              <div className="comparison-summary">
                <div>
                  <span>Changed moves</span>
                  <b>{changedIds.size}</b>
                </div>
                <div>
                  <span>Competing services harmed</span>
                  <b>
                    {candidate.impact
                      ?.filter((i) => (i.delta || 0) < 0)
                      .map((i) => serviceName(i.id))
                      .join(", ") || "None projected"}
                  </b>
                </div>
                <div>
                  <span>Unscheduled cargo</span>
                  <b>
                    {candidate.services?.reduce((n, c) => n + c.unscheduled, 0)}
                  </b>
                </div>
              </div>
              <div className="schedule-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Departure</th>
                      <th>Projected on time</th>
                      <th>Change from baseline</th>
                      <th>Unscheduled</th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidate.services!.map((co) => {
                      const delta = candidate.impact?.find(
                        (x) => x.id === co.id,
                      )?.delta;
                      return (
                        <tr
                          key={co.id}
                          className={
                            co.id === departure ? "focus-departure" : ""
                          }
                        >
                          <td>
                            {serviceName(co.id)} · cutoff {clock(co.cutoff)}
                          </td>
                          <td>
                            {co.on_time}/{co.total}{" "}
                            {co.on_time === co.total
                              ? "· complete manifest"
                              : ""}
                          </td>
                          <td>
                            {delta === null || delta === undefined
                              ? "—"
                              : delta > 0
                                ? `+${delta} protected`
                                : delta < 0
                                  ? `${Math.abs(delta)} fewer protected`
                                  : "No change"}
                          </td>
                          <td>{co.unscheduled}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <details>
                <summary>Map of selected bookings</summary>
                <CaseMap
                  s={s}
                  mode="proposal"
                  jobs={candidate.rows
                    .filter(
                      (r) =>
                        !caseJobs ||
                        caseJobs.includes(r.job_id) ||
                        r.job_id === selectedJob,
                    )
                    .sort((a, b) => a.start - b.start)
                    .map((r) => ({
                      ...s.jobs.find((j) => j.id === r.job_id)!,
                      source_id: r.source_id,
                      target_id: r.target_id,
                    }))}
                  selected={selectedJob || ""}
                  select={select}
                />
              </details>
              <div className="section-heading">
                <h4>Equipment bookings</h4>
                <button
                  aria-pressed={fullHorizon}
                  onClick={() => setFullHorizon(!fullHorizon)}
                >
                  {fullHorizon ? "Focus departure window" : "Show full horizon"}
                </button>
              </div>
              <p className="micro">
                Proposed simultaneous bundles · select a bar to highlight every
                required resource.
              </p>
              <ScheduleTimeline
                s={s}
                rows={candidate.rows}
                start={result.base_minute}
                end={fullHorizon ? result.end_minute : focusEnd}
                select={select}
                selectedJob={selectedJob}
                departure={departure}
              />
              <div className="section-heading">
                <h4>
                  {showAllWork || candidate.key === "baseline"
                    ? "Work order"
                    : "Changed & selected work"}
                </h4>
                <button
                  onClick={() => setShowAllWork(!showAllWork)}
                  aria-pressed={showAllWork}
                >
                  {showAllWork ? "Show changes" : "Show all work"}
                </button>
              </div>
              <p className="micro">
                {
                  (
                    result.candidates.find((c) => c.key === "baseline")?.rows ||
                    []
                  ).filter(
                    (b) => !candidate.rows.some((r) => r.job_id === b.job_id),
                  ).length
                }{" "}
                baseline moves omitted from this alternative.
              </p>
              <div className="schedule-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Move / purpose</th>
                      <th>Booked equipment</th>
                      <th>Planned stages</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...visibleRows]
                      .sort(
                        (a, b) =>
                          a.start - b.start || a.job_id.localeCompare(b.job_id),
                      )
                      .map((r) => (
                        <tr key={r.job_id}>
                          <td>
                            {clock(r.start)}–{clock(r.end)}
                            {r.frozen && <small> · already underway</small>}
                          </td>
                          <td>
                            <button
                              className="text-button"
                              onClick={() => select(r.job_id)}
                            >
                              {cargoName(r.container_id)}
                            </button>
                            <br />
                            {placeName(s, r.source_id)} →{" "}
                            {placeName(s, r.target_id)}
                            <small>
                              {changes
                                .find((c) => c.job_id === r.job_id)
                                ?.changes.join(" · ") || "Unchanged"}
                            </small>
                          </td>
                          <td>
                            {r.resources
                              .map((e) => equipmentName(s, e))
                              .join(" + ")}
                          </td>
                          <td>
                            {r.stages.map((st) => (
                              <span className="schedule-stage" key={st.name}>
                                {st.name} {clock(st.start)}–{clock(st.end)}
                              </span>
                            ))}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              <details>
                <summary>
                  {candidate.unresolved?.length || 0} work orders not scheduled
                  · inspect why
                </summary>
                {candidate.unresolved?.map((j) => (
                  <p key={j.job_id}>
                    <button
                      className="text-button"
                      onClick={() => select(j.job_id)}
                    >
                      {cargoName(j.container_id)} · {j.job_id}
                    </button>{" "}
                    — {j.reasons.map((r) => readable(s, r)).join("; ")}
                  </p>
                ))}
              </details>
            </section>
          )}
          <details className="panel">
            <summary>Assumptions, solver status and limits</summary>
            <ul>
              {result.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
            <p>
              {result.solver.engine}: {result.solver.status} ·{" "}
              {result.solver.elapsed_seconds}s · {result.solver.scope}
            </p>
            {result.solver.passes.map((p) => (
              <p key={p.objective}>
                {p.objective}: {p.status} · value {p.value ?? "no incumbent"} ·
                bound {p.bound}
              </p>
            ))}
            <p>
              A solver timeout is not proof that recovery is impossible.
              Rejected candidates cannot be approved; validated heuristics
              remain available.
            </p>
          </details>
        </>
      )}
      {confirm && (
        <div className="modal-backdrop" onClick={() => setConfirm(null)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="schedule-review"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Escape") setConfirm(null);
              if (e.key === "Tab") {
                const nodes = Array.from(
                  e.currentTarget.querySelectorAll<HTMLButtonElement>(
                    "button:not(:disabled)",
                  ),
                );
                const first = nodes[0],
                  last = nodes.at(-1);
                if (e.shiftKey && document.activeElement === first) {
                  e.preventDefault();
                  last?.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                  e.preventDefault();
                  first?.focus();
                }
              }
            }}
          >
            <h2 id="schedule-review">Approve this work sequence?</h2>
            <p>
              {confirm.title} · basis revision {latest?.base_revision}
            </p>
            <p>
              {confirm.rows.filter((r) => !r.frozen).length} future moves will
              be booked. Existing in-progress moves remain frozen. This replaces
              future bookings from the previous schedule.
            </p>
            <ul>
              {confirm.impact?.map((co) => (
                <li key={co.id}>
                  {serviceName(co.id)}: {co.on_time}/{co.total} projected on
                  time ·{" "}
                  {co.delta === 0
                    ? "unchanged"
                    : `${co.delta ?? "—"} vs baseline`}
                </li>
              ))}
            </ul>
            <p>
              No cargo moves until the clock advances and the simulator
              acknowledges dispatch. Changed state will reject approval.
            </p>
            <div className="schedule-actions">
              <button
                autoFocus
                className="secondary"
                onClick={() => setConfirm(null)}
              >
                Cancel
              </button>
              <button
                className="primary"
                disabled={stale || s.running}
                onClick={() => {
                  command({
                    action: "approve_schedule",
                    plan_id: confirm.plan_id,
                  });
                  setConfirm(null);
                }}
              >
                Approve resource bookings
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}

export function ScheduleTimeline({
  s,
  rows,
  start,
  end,
  select,
  selectedJob,
  departure,
  mode = "proposal",
}: {
  mode?: "proposal" | "approved";
  s: State;
  rows: Booking[];
  start: number;
  end: number;
  select: (id: string) => void;
  selectedJob?: string;
  departure?: string;
}) {
  const laneLabel = (r: Booking & { displayStage?: string }, eid: string) => {
    const job = s.jobs.find((j) => j.id === r.job_id);
    if (!s.movement || mode === "proposal")
      return reservationLabel(mode, s.schedule?.status, job?.status, r.frozen);
    if (job?.status === "completed") return "Completed";
    if (
      job?.status === "running" &&
      job.resources.includes(eid) &&
      job.movement_stages?.[job.stage_index || 0]?.name === r.displayStage
    )
      return "Occupied";
    if (!["approved", "executing"].includes(s.schedule?.status || ""))
      return "Released";
    return r.end <= s.minute ? "Completed" : "Booked";
  };
  const [localSelection, setLocalSelection] = useState("");
  const active = selectedJob || localSelection;
  const selected = rows.find((r) => r.job_id === active);
  const span = Math.max(1, end - start);
  const cutoff = s.commitments.find((c) => c.id === departure)?.cutoff;
  const style = (a: number, b: number) => ({
    left: `${Math.max(0, ((a - start) / span) * 100)}%`,
    width: `${Math.max(0, ((Math.min(b, end) - Math.max(a, start)) / span) * 100)}%`,
  });
  const markers = [
    { at: s.minute, label: "Now", kind: "now" },
    ...(cutoff === undefined
      ? []
      : [{ at: cutoff, label: `Cutoff ${clock(cutoff)}`, kind: "cutoff" }]),
  ].filter((m) => m.at >= start && m.at <= end);
  return (
    <div className="booking-view">
      <div className="booking-legend">
        <span>Shaded: unavailable</span>
        <span>Teal: {mode === "proposal" ? "proposed" : "booked"}</span>
        <span>
          Amber: {mode === "proposal" ? "frozen at comparison" : "occupied"}
        </span>
        {mode === "approved" && <span>Grey: completed / released</span>}
        <span>Outline: selected bundle</span>
      </div>
      <div
        className="schedule-timeline"
        aria-label="Equipment reservation timeline"
      >
        <div className="booking-axis">
          <span>Equipment</span>
          <div>
            {[0, 0.25, 0.5, 0.75, 1].map((f) => (
              <span key={f} style={{ left: `${f * 100}%` }}>
                {clock(Math.round(start + span * f))}
              </span>
            ))}
          </div>
        </div>
        {["quay", "yard", "tractor", "gate"].map((kind) => (
          <div key={kind}>
            <div className="booking-group">
              {
                {
                  quay: "Quay cranes",
                  yard: "Yard cranes",
                  tractor: "Terminal tractors",
                  gate: "Gate handling",
                }[kind]
              }
            </div>
            {s.equipment
              .filter((e) => e.kind === kind)
              .map((e) => (
                <div className="booking-lane" key={e.id}>
                  <span>
                    {equipmentName(s, e.id)}
                    {e.status === "failed" && (
                      <small className="equipment-failed">Failed</small>
                    )}
                  </span>
                  <div className="booking-track">
                    {(
                      s.availability || [
                        {
                          equipment_id: e.id,
                          start_minute: start,
                          end_minute: end,
                        },
                      ]
                    )
                      .filter(
                        (w) =>
                          w.equipment_id === e.id &&
                          w.end_minute > start &&
                          w.start_minute < end,
                      )
                      .map((w, i) => (
                        <span
                          key={i}
                          className="booking-available"
                          style={style(w.start_minute, w.end_minute)}
                        />
                      ))}
                    {markers.map((m) => (
                      <span
                        key={m.kind}
                        className={`booking-marker ${m.kind}`}
                        style={{ left: `${((m.at - start) / span) * 100}%` }}
                        title={m.label}
                      />
                    ))}
                    {rows
                      .flatMap((r) =>
                        s.movement
                          ? r.stages
                              .filter((p) => p.resources?.includes(e.id))
                              .map((p, i) => ({
                                ...r,
                                start: p.start,
                                end: p.end,
                                displayStage: p.name,
                                displayKey: `${r.job_id}:${i}`,
                              }))
                          : [{ ...r, displayStage: "", displayKey: r.job_id }],
                      )
                      .filter(
                        (r) =>
                          r.resources.includes(e.id) &&
                          r.end > start &&
                          r.start < end,
                      )
                      .map((r) => (
                        <button
                          key={r.displayKey}
                          className={`${["Occupied", "Frozen at comparison"].includes(laneLabel(r, e.id)) ? "frozen" : ""} ${["Completed", "Released"].includes(laneLabel(r, e.id)) ? "released-booking" : ""} ${r.job_id === active ? "selected-bundle" : ""}`}
                          style={style(r.start, r.end)}
                          onClick={() => {
                            setLocalSelection(r.job_id);
                            select(r.job_id);
                          }}
                          aria-pressed={r.job_id === active}
                          aria-label={`${equipmentName(s, e.id)}: ${r.displayStage} ${cargoName(r.container_id)}, ${clock(r.start)} to ${clock(r.end)}`}
                          title={`${r.displayStage} · ${laneLabel(r, e.id)} · ${cargoName(r.container_id)} · ${r.source_id} → ${r.target_id} · ${clock(r.start)}–${clock(r.end)}`}
                        >
                          <span>
                            {Number(r.container_id.replace("CT-", "")) ||
                              r.container_id}
                          </span>
                        </button>
                      ))}
                  </div>
                </div>
              ))}
          </div>
        ))}
      </div>
      <div className="booking-legend">
        {markers.map((m) => (
          <span key={m.kind}>{m.label}</span>
        ))}
      </div>
      {selected && (
        <div className="booking-selection">
          <b>
            {reservationLabel(
              mode,
              s.schedule?.status,
              s.jobs.find((j) => j.id === selected.job_id)?.status,
              selected.frozen,
            )}{" "}
            · {cargoName(selected.container_id)} · {clock(selected.start)}–
            {clock(selected.end)}
          </b>
          <span>
            {placeName(s, selected.source_id)} →{" "}
            {placeName(s, selected.target_id)}
          </span>
          <span>
            {selected.resources.map((id) => equipmentName(s, id)).join(" + ")}
          </span>
          {s.movement && (
            <div className="movement-stages">
              {selected.stages.map((p, i) => (
                <div key={i}>
                  <b>{p.name}</b>
                  <br />
                  {clock(p.start)}–{clock(p.end)}
                  <br />
                  {p.resources?.map((id) => equipmentName(s, id)).join(" + ")}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
