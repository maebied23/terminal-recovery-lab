import { useState } from "react";
import type { State, Requirement } from "./types";
import { clock } from "./types";
import {
  cargoName,
  serviceName,
  equipmentName,
  placeName,
  readable,
} from "./departure";
import "./diagnosis.css";
export type Workspace =
  | "Operations"
  | "Work & commitments"
  | "Recovery"
  | "Scenario lab"
  | "Evidence";
export type Finding = {
  code: string;
  reason: string;
  rule: string;
  action: string;
  page: Workspace;
  requires_review: boolean;
  facts: Record<string, unknown>;
};
export type VisitDiagnosis = {
  container_id: string;
  visit_id: string;
  commitment_id: string;
  readiness: string;
  attention: boolean;
  next_job_id: string | null;
  job_ids: string[];
  final_ids: string[];
  cutoff: number;
  integrity: string[];
  edges: {
    job_id: string;
    predecessor_id: string;
    details: { reason?: string; origin?: string };
  }[];
  mismatches: {
    job_id: string;
    planned_pickup: string;
    observed_position: string | null;
  }[];
  chain: {
    job_id: string;
    container_id: string;
    source_id: string;
    target_id: string;
    equipment_id: string;
    status: string;
    issues: Finding[];
    requirements: Requirement[];
  }[];
};
export type Diagnosis = {
  run: string;
  revision: number;
  minute: number;
  historical: boolean;
  dataset?: { title: string };
  departures: {
    commitment_id: string;
    cutoff: number;
    total: number;
    ready: number;
    on_time: number;
    late: number;
    underway: number;
    blocked: number;
    review: number;
    missed: number;
    attention: number;
  }[];
  manifest: VisitDiagnosis[];
  calendar: {
    equipment_id: string;
    status: string;
    active_job: string | null;
    commitments: string[];
    activity: {
      job_id: string;
      container_id: string;
      start: number;
      end: number;
      status: string;
      gap_before: number | null;
    }[];
    windows: {
      start: number;
      end: number;
      source: string;
      permits_dispatch: boolean;
    }[];
  }[];
  receipts: {
    id: number;
    entity_id: string | null;
    field: string;
    status: string;
    reason: string;
    observed_minute: number | null;
    receive_minute: number;
    applied_revision: number;
  }[];
  limitations: string[];
};

export function CaseContext({
  s,
  report,
  departure,
  cargo,
  chooseDeparture,
  chooseCargo,
  navigate,
  page,
  historical,
}: {
  s: State;
  report: Diagnosis | null;
  departure: string;
  cargo: string;
  chooseDeparture: (id: string) => void;
  chooseCargo: (id: string) => void;
  navigate: (page: Workspace) => void;
  page: Workspace;
  historical: boolean;
}) {
  const rows = s.containers.filter((c) => c.commitment_id === departure);
  return (
    <section className="case-context" aria-label="Shared decision case">
      <div>
        <span className="eyebrow">DECISION CONTEXT</span>
        <strong>Selected case</strong>
        <small>
          {historical ? "Historical · read only" : "Observed state"} ·{" "}
          {clock(s.minute)} · revision {s.revision} ·{" "}
          {s.dataset?.title || "Synthetic shift"}
        </small>
      </div>
      <div className="case-selectors">
        <label>
          Decision departure
          <select
            aria-label="Decision departure"
            value={departure}
            onChange={(e) => chooseDeparture(e.target.value)}
          >
            {s.commitments.map((c) => (
              <option key={c.id} value={c.id}>
                {serviceName(c.id)} · {clock(c.cutoff)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Decision cargo
          <select
            aria-label="Decision cargo"
            value={cargo}
            onChange={(e) => chooseCargo(e.target.value)}
          >
            {!rows.length && <option value="">No committed cargo</option>}
            {rows.map((c) => (
              <option key={c.id} value={c.id}>
                {cargoName(c.id)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <nav aria-label="Follow decision">
        <button
          aria-current={page === "Operations" ? "page" : undefined}
          onClick={() => navigate("Operations")}
        >
          Open case
        </button>
        <button
          aria-current={page === "Work & commitments" ? "page" : undefined}
          onClick={() => navigate("Work & commitments")}
        >
          Terminal queue
        </button>
        <button
          aria-current={page === "Evidence" ? "page" : undefined}
          onClick={() => navigate("Evidence")}
        >
          Source evidence
        </button>
        <button
          disabled={historical}
          aria-current={page === "Recovery" ? "page" : undefined}
          onClick={() => navigate("Recovery")}
        >
          Compare schedules
        </button>
      </nav>
      {report && (
        <p className="case-status">
          {report.manifest.find((r) => r.container_id === cargo)?.readiness ||
            "No cargo diagnosis"}{" "}
          · revision {s.revision}{" "}
          {historical ? "Return to current state before recovery." : ""}
        </p>
      )}
    </section>
  );
}

export function DepartureAttention({
  report,
  choose,
}: {
  report: Diagnosis;
  choose: (id: string) => void;
}) {
  return (
    <section className="diagnosis-attention" aria-label="Departure attention">
      <div>
        <h3>Which departure needs attention?</h3>
        <p>
          Attention first, then cutoff. Counts are cargo visits, not moves or
          probabilities.
        </p>
      </div>
      <div className="attention-cards">
        {report.departures.map((d) => (
          <button key={d.commitment_id} onClick={() => choose(d.commitment_id)}>
            <strong>
              {serviceName(d.commitment_id)} <span>{clock(d.cutoff)}</span>
            </strong>
            <b>
              {d.attention} need attention <small>/ {d.total} cargo</small>
            </b>
            <small>
              {d.ready} next move ready · {d.on_time} delivered on time ·{" "}
              {d.review} need review
            </small>
          </button>
        ))}
      </div>
    </section>
  );
}

export function DiagnosisPanel({
  s,
  report,
  row,
  navigate,
  inspect,
  historical,
}: {
  s: State;
  report: Diagnosis;
  row: VisitDiagnosis | undefined;
  navigate: (page: Workspace) => void;
  inspect: (id: string) => void;
  historical: boolean;
}) {
  const [tab, setTab] = useState("Decision brief");
  if (!row)
    return (
      <section className="diagnosis-panel">
        No committed cargo in this case.
      </section>
    );
  const findings = row.chain
    .filter((d) => d.status !== "completed")
    .flatMap((d) => d.issues.map((i) => ({ ...i, job: d })));
  const review = findings.filter((i) => i.requires_review);
  const next = row.chain.find((d) => d.job_id === row.next_job_id);
  const lead = review[0] || next?.issues[0];
  const ids = new Set(
    row.chain.flatMap((d) => [
      d.container_id,
      d.equipment_id,
      ...d.requirements.flatMap((r) => [...r.eligible, ...r.reserved]),
    ]),
  );
  const lanes = report.calendar.filter((e) => ids.has(e.equipment_id));
  const horizon = Math.max(60, row.cutoff + 15, report.minute + 10);
  const receipts = report.receipts.filter(
    (r) => r.entity_id && ids.has(r.entity_id),
  );
  return (
    <section className="diagnosis-panel" aria-label="Decision diagnosis">
      <header>
        <div>
          <span className="eyebrow">FACTS → CONSTRAINT → NEXT REVIEW</span>
          <h3>
            {cargoName(row.container_id)} · {row.readiness}
          </h3>
        </div>
        <span className="diagnosis-revision">r{report.revision}</span>
      </header>
      <div className="diagnosis-tabs" role="group" aria-label="Diagnosis views">
        {["Decision brief", "Equipment windows", "Evidence links"].map((t) => (
          <button key={t} aria-pressed={tab === t} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      {tab === "Decision brief" && (
        <>
          <div
            className={`diagnosis-next ${review.length ? "needs-review" : ""}`}
          >
            <strong>
              {review.length
                ? "Work instruction needs reconciliation"
                : lead
                  ? readable(s, lead.reason)
                  : next
                    ? next.status === "running"
                      ? "Handling is underway"
                      : "The next move can proceed under the current checks"
                    : row.readiness}
            </strong>
            <p>
              {review.length
                ? review
                    .map(
                      (i) =>
                        `${cargoName(i.job.container_id)} is observed at ${placeName(s, i.job.issues.find((x) => x.code === "plan_mismatch")?.facts.location_id as string | null)}, but its instruction starts at ${placeName(s, i.job.source_id)}.`,
                    )
                    .join(" ")
                : next
                  ? `${cargoName(next.container_id)}: ${placeName(s, next.source_id)} → ${placeName(s, next.target_id)}. ${next.status === "running" ? "This work has started." : "This is the next prerequisite or delivery move."}`
                  : "Inspect the recorded delivery and cutoff."}
            </p>
            <button
              disabled={historical && lead?.page === "Recovery"}
              onClick={() => navigate(lead?.page || "Work & commitments")}
            >
              {lead?.action || "Inspect required work"}
            </button>
            {review.length > 0 && (
              <small>
                Position evidence does not complete or cancel a work order.
                Review it before planning recovery.
              </small>
            )}
          </div>
          {row.integrity.map((i) => (
            <p role="alert" key={i}>
              {readable(s, i)}
            </p>
          ))}
          <details className="diagnosis-chain">
            <summary>Trace required work · {row.chain.length} moves</summary>
            <ol>
              {row.chain.map((d) => (
                <li key={d.job_id}>
                  <strong>
                    {d.status === "completed" ? "Completed: " : ""}
                    {cargoName(d.container_id)} · {placeName(s, d.source_id)} →{" "}
                    {placeName(s, d.target_id)}
                  </strong>
                  <small>
                    {equipmentName(s, d.equipment_id)} · {d.status} ·{" "}
                    <code>{d.job_id}</code>
                  </small>
                  {row.edges
                    .filter((e) => e.job_id === d.job_id)
                    .map((e) => (
                      <p key={e.predecessor_id}>
                        Requires {readable(s, e.predecessor_id)}:{" "}
                        {e.details.reason || "Recorded prerequisite"}{" "}
                        <small>
                          Origin: {e.details.origin || "recorded work plan"}
                        </small>
                      </p>
                    ))}
                  {d.issues.map((i) => (
                    <details key={i.reason}>
                      <summary>
                        {readable(s, i.reason)}
                        {i.code === "awaiting_transfer"
                          ? " · expected upstream delivery"
                          : ""}
                      </summary>
                      <p>
                        {i.action} · rule {i.rule}
                      </p>
                      <button onClick={() => inspect(d.container_id)}>
                        Inspect supporting input
                      </button>
                      <pre>{JSON.stringify(i.facts, null, 2)}</pre>
                    </details>
                  ))}
                </li>
              ))}
            </ol>
          </details>
          <p className="diagnosis-footnote">
            A ready prerequisite is not a promise that all remaining work will
            meet the cutoff. Existing dependency instructions remain in force
            until explicitly reconciled.
          </p>
        </>
      )}
      {tab === "Equipment windows" && (
        <>
          <p>
            Compatible resources for this chain. Availability, assigned
            equipment and recorded use are different facts. Future bookings are
            not implemented.
          </p>
          <div className="equipment-lanes">
            {lanes.map((e) => (
              <article key={e.equipment_id}>
                <h4>
                  {equipmentName(s, e.equipment_id)}{" "}
                  <span>
                    {e.status === "failed"
                      ? "Unavailable"
                      : e.active_job
                        ? "Occupied"
                        : "No active move"}
                  </span>
                </h4>
                <div
                  className="availability-track"
                  aria-label={`${equipmentName(s, e.equipment_id)} availability`}
                >
                  {e.windows.map((w, i) => (
                    <span
                      key={i}
                      className={w.permits_dispatch ? "permitted" : ""}
                    >
                      {clock(w.start)}–{clock(w.end)} ·{" "}
                      {w.permits_dispatch ? "within shift" : "outside shift"}
                    </span>
                  ))}
                  {!e.windows.length && (
                    <span>Legacy shift: no published window recorded</span>
                  )}
                </div>
                <div className="calendar-axis">
                  <span>08:00</span>
                  <span>{clock(horizon)}</span>
                </div>
                <div
                  className="calendar-plot"
                  role="img"
                  aria-label={`${equipmentName(s, e.equipment_id)}: published windows outlined, recorded work solid, observation at ${clock(report.minute)}`}
                >
                  {e.windows
                    .filter((w) => w.start < horizon)
                    .map((w, i) => (
                      <span
                        key={`w${i}`}
                        className="calendar-window"
                        style={{
                          left: `${(w.start / horizon) * 100}%`,
                          width: `${((Math.min(w.end, horizon) - w.start) / horizon) * 100}%`,
                        }}
                      />
                    ))}
                  {e.activity
                    .filter((a) => a.start < horizon)
                    .map((a) => (
                      <span
                        key={a.job_id}
                        className="calendar-actual"
                        title={`${cargoName(a.container_id)}: ${clock(a.start)}–${clock(a.end)}`}
                        style={{
                          left: `${(a.start / horizon) * 100}%`,
                          width: `${Math.max(0.5, ((Math.min(a.end, horizon) - a.start) / horizon) * 100)}%`,
                        }}
                      />
                    ))}
                  <span
                    className="calendar-now"
                    style={{ left: `${(report.minute / horizon) * 100}%` }}
                  />
                </div>
                <small>
                  Outline: published shift · solid: recorded use · marker:
                  observed time. Only the displayed horizon is drawn.
                </small>
                <p>
                  Assigned/recorded active work connects:{" "}
                  {e.commitments.map(serviceName).join(", ") || "none"}.
                  Compatibility alone is not an assignment.
                </p>
                {e.activity.length ? (
                  <ul>
                    {e.activity.map((a) => (
                      <li key={a.job_id}>
                        {cargoName(a.container_id)} · {clock(a.start)}–
                        {clock(a.end)}{" "}
                        {a.status === "running"
                          ? "(observed so far)"
                          : "(completed)"}
                        {a.gap_before !== null && (
                          <small>
                            {" "}
                            · {a.gap_before} min gap since previous recorded use
                          </small>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <small>No recorded handling activity yet.</small>
                )}
                <button onClick={() => inspect(e.equipment_id)}>
                  Inspect equipment evidence
                </button>
              </article>
            ))}
          </div>
        </>
      )}
      {tab === "Evidence links" && (
        <>
          <p>
            Only deliveries known at revision {report.revision}. Queued future
            messages do not appear here.
          </p>
          <button onClick={() => inspect(row.container_id)}>
            Open original rows and input provenance
          </button>
          {receipts.length ? (
            <ul className="diagnosis-receipts">
              {receipts.map((r) => (
                <li key={r.id}>
                  <strong>
                    {r.entity_id?.startsWith("CT-")
                      ? cargoName(r.entity_id)
                      : equipmentName(
                          s,
                          r.entity_id || "Unknown identity",
                        )}{" "}
                    · {r.status}
                  </strong>
                  <span>
                    Observed{" "}
                    {r.observed_minute === null
                      ? "unknown"
                      : clock(r.observed_minute)}{" "}
                    · received {clock(r.receive_minute)} · known r
                    {r.applied_revision}
                  </span>
                  <p>{r.reason}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p>
              No delivered feed observations for this chain. Its current facts
              come from the starting state and recorded execution.
            </p>
          )}
          <p className="diagnosis-footnote">
            Rejected observations are evidence of disagreement; they are not
            accepted operational facts.
          </p>
        </>
      )}
    </section>
  );
}
