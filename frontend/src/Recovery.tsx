import { ScheduleRecovery } from "./ScheduleRecovery";
import { cargoName } from "./departure";
import type { AccessProposal } from "./types";
import { WorkCard } from "./RelationPanels";
import {
  FlaskConical,
  ArrowRight,
  CheckCircle2,
  RefreshCw,
  Download,
  AlertTriangle,
} from "lucide-react";
import { useState } from "react";
import type { State, Experiment, CommandResult, Candidate } from "./types";
import { Badge, Score } from "./components";
export function Recovery({
  s,
  experiments,
  commands,
  compare,
  approve,
  select,
  cancel,
  run,
  request,
  command,
  caseCargo,
  departure,
}: {
  caseCargo: string;
  departure: string;
  request: (path: string, body?: unknown) => Promise<any>;
  command: (cmd: Record<string, unknown>) => void;
  s: State;
  experiments: Experiment[];
  commands: CommandResult[];
  compare: () => void;
  approve: (id: string) => void;
  select: (id: string) => void;
  cancel: (id: string) => void;
  run: string;
}) {
  const [access, setAccess] = useState<AccessProposal | null>(null);
  const [accessError, setAccessError] = useState("");
  const preview = async (id: string) => {
    setAccess(null);
    setAccessError("");
    try {
      setAccess(await request(`/api/access/${id}?run=${run}`));
    } catch (e) {
      setAccessError(String(e));
    }
  };
  const accepted = experiments
    .flatMap((e) => e.result?.candidates || [])
    .find((c) => c.plan_id === s.plan_id);
  const [detail, setDetail] = useState<Candidate | null>(null);
  const active = experiments.find((e) =>
    ["queued", "running"].includes(e.status),
  );
  const latest = experiments.find((e) => e.status === "completed");
  const stale = latest && latest.base_revision !== s.revision;
  const candidates = latest?.result?.candidates || [];
  return (
    <>
      <ScheduleRecovery
        s={s}
        run={run}
        departure={departure}
        request={request}
        command={command}
        select={select}
      />
      <details className="panel">
        <summary>
          Additional tools · access relocations and policy experiments
        </summary>
        <div className="page-heading">
          <div>
            <div className="eyebrow">DECISION WORKSPACE</div>
            <h1>Recovery</h1>
            <p>
              Compare consequences, inspect constraints, then approve a recovery
              policy.
            </p>
          </div>
          <button
            className="primary"
            onClick={compare}
            disabled={!!active || s.running || !!s.schedule}
          >
            <FlaskConical size={17} />
            {active ? "Comparing…" : "Compare plans"}
          </button>
        </div>
        <section className="panel">
          <h3>Clear blocked yard access</h3>
          <p>
            Preview relocations using the observed stack. Existing access work
            is inspected, not duplicated. Approval creates jobs; it never moves
            containers.
          </p>
          {s.jobs
            .filter(
              (j) =>
                j.status === "queued" &&
                j.blockers.includes("Another container is stacked above"),
            )
            .sort(
              (a, b) =>
                Number(b.container_id === caseCargo) -
                Number(a.container_id === caseCargo),
            )
            .map((j) => (
              <div className="readiness-item" key={j.id}>
                <WorkCard j={j} select={select} />
                <button
                  className="secondary"
                  disabled={s.running || !!s.schedule}
                  onClick={() => preview(j.id)}
                >
                  Preview access plan for {cargoName(j.container_id)}
                </button>
              </div>
            ))}
          {!s.jobs.some(
            (j) =>
              j.status === "queued" &&
              j.blockers.includes("Another container is stacked above"),
          ) && <p>No observed yard-access blockage in this state.</p>}
          {accessError && <p role="alert">{accessError}</p>}
          {access && (
            <div className="access-preview">
              <h4>Proposed work · basis r{access.base_revision}</h4>
              {access.moves.map((m, i) => (
                <p key={m.container_id}>
                  <b>
                    {i + 1}. Relocate {m.container_id}
                  </b>
                  <br />
                  {m.source_id} → {m.target_id} · {m.equipment_id}
                  <br />
                  {m.reason}
                </p>
              ))}
              <ul>
                {access.assumptions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
              <button
                className="primary"
                disabled={s.running || s.revision !== access.base_revision}
                onClick={() => {
                  command({
                    action: "approve_access",
                    entity_id: access.job_id,
                    proposal_token: access.token,
                  });
                  setAccess(null);
                }}
              >
                Approve these prerequisite jobs
              </button>
              {s.revision !== access.base_revision && (
                <p>State changed. Preview again.</p>
              )}
            </div>
          )}
        </section>
        {accepted && (
          <section className="panel">
            <div className="section-heading">
              <h3>Approved policy · {accepted.title}</h3>
              <Badge
                value={s.metrics.pending ? "executing" : "outcome recorded"}
              />
            </div>
            <div className="feedback-grid">
              <div>
                <span className="eyebrow">
                  SIMULATED PROJECTION AT APPROVAL
                </span>
                <Score m={accepted.metrics} />
              </div>
              <div>
                <span className="eyebrow">OBSERVED IN THIS RUN SO FAR</span>
                <Score m={s.metrics} />
              </div>
            </div>
            <p className="micro">
              {s.metrics.pending} commitments remain unresolved. Projection and
              observed outcome are separate; later failures or authority updates
              can change the result.
            </p>
          </section>
        )}
        <div className="notice">
          <FlaskConical size={19} />
          <p>
            <b>Paired simulation, not a confidence score.</b> Each policy sees
            the same per-job duration samples. Five replications, a 180-minute
            horizon, and explicit synthetic assumptions. Pause the clock before
            comparing.
          </p>
        </div>
        {active && (
          <div className="panel experiment-progress">
            <div>
              <b>Testing policies against the same conditions</b>
              <button className="text-button" onClick={() => cancel(active.id)}>
                Cancel experiment
              </button>
            </div>
            <div className="progress">
              <i style={{ width: `${active.progress}%` }} />
            </div>
            <span>
              {active.progress}% · {active.status}
            </span>
          </div>
        )}
        {!latest && !active && (
          <div className="empty large">
            <FlaskConical size={35} />
            <h3>A recommendation should earn your trust.</h3>
            <p>
              Compare the current schedule with rail-first, balanced-deadline
              and vessel-first alternatives. Unresolved holds and impossible
              moves stay visible.
            </p>
            <button
              className="secondary"
              onClick={compare}
              disabled={s.running || !!s.schedule}
            >
              Run the first comparison <ArrowRight size={16} />
            </button>
          </div>
        )}
        {latest && (
          <>
            <div className="section-heading">
              <h3>
                Recovery alternatives{" "}
                <span>from revision {latest.base_revision}</span>
              </h3>
              <a
                className="text-button"
                href={`/api/experiments/${latest.id}/export?run=${run}`}
                target="_blank"
                rel="noreferrer"
              >
                <Download size={15} /> Export manifest & results
              </a>
            </div>
            {stale && (
              <div className="notice warning">
                <AlertTriangle size={18} />
                <p>
                  State has changed since this comparison. Results remain as
                  evidence; run a fresh comparison before approving.
                </p>
              </div>
            )}
            <div className="candidate-grid">
              {candidates.map((c, i) => {
                const recommended = latest.result?.recommended === c.policy;
                return (
                  <article
                    className={`candidate ${recommended ? "recommended" : ""}`}
                    key={c.policy}
                  >
                    <div className="candidate-kicker">
                      {i === 0
                        ? "BASELINE"
                        : recommended
                          ? "BEST UNDER THESE ASSUMPTIONS"
                          : "ALTERNATIVE"}
                      {recommended && <CheckCircle2 size={16} />}
                    </div>
                    <h3>{c.title}</h3>
                    <Score m={c.metrics} />
                    <div className="range">
                      <span>On-time P10–P90 scenario range</span>
                      <b>
                        {c.interval[0]}–{c.interval[1]} / {s.metrics.total}
                      </b>
                    </div>
                    <p>
                      {i === 0
                        ? "Current priority and assignments held as the reference."
                        : `${c.delta_on_time >= 0 ? "+" : ""}${c.delta_on_time} on-time cargo vs baseline · ${c.changes.length} assignment changes.`}
                    </p>
                    <button
                      className="text-button"
                      onClick={() => setDetail(c)}
                    >
                      Inspect tradeoffs & constraints <ArrowRight size={14} />
                    </button>
                    {c.plan_id && (
                      <button
                        className={
                          recommended ? "primary full" : "secondary full"
                        }
                        disabled={
                          !!stale ||
                          s.running ||
                          commands.some(
                            (cmd) =>
                              cmd.payload.plan_id === c.plan_id &&
                              cmd.status !== "rejected",
                          )
                        }
                        onClick={() => approve(c.plan_id!)}
                      >
                        Approve policy
                      </button>
                    )}
                  </article>
                );
              })}
            </div>
            <div className="panel">
              <div className="section-heading">
                <h3>Outcome over simulated time</h3>
                <span>First matched seed · completed outbound commitments</span>
              </div>
              <ComparisonChart candidates={candidates} />
              <p className="micro">
                {latest.result?.warning} Computed in{" "}
                {latest.result?.elapsed_seconds}s. Approval changes priorities
                and queued assignments; normal dispatch still checks every
                constraint.
              </p>
            </div>
          </>
        )}
        {experiments[0]?.status === "failed" && (
          <div className="notice warning">
            Experiment failed: {experiments[0].error}. Check server logs and
            retry.
          </div>
        )}
        <div className="panel">
          <div className="section-heading">
            <h3>Command & execution ledger</h3>
            <span>Acceptance ≠ physical completion</span>
          </div>
          {!commands.length ? (
            <p className="muted">
              Approved actions will appear here, including rejected and failed
              deliveries.
            </p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Command</th>
                  <th>Target</th>
                  <th>Delivery</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {commands.slice(0, 8).map((c) => (
                  <tr key={c.id}>
                    <td>{c.payload.action.replaceAll("_", " ")}</td>
                    <td>
                      {c.payload.entity_id ||
                        c.payload.plan_id?.slice(0, 8) ||
                        "Terminal clock"}
                    </td>
                    <td>
                      <Badge value={c.status} />
                    </td>
                    <td>
                      {c.result?.error ||
                        (c.result?.revision !== undefined
                          ? `Acknowledged at revision ${c.result.revision}`
                          : "Awaiting worker")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </details>
      {detail && (
        <div className="modal-backdrop" onClick={() => setDetail(null)}>
          <section className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="section-heading">
              <h2>{detail.title}</h2>
              <button className="secondary" onClick={() => setDetail(null)}>
                Close
              </button>
            </div>
            <p>{detail.explanation}</p>
            <h4>Assignment changes</h4>
            {detail.changes.length ? (
              detail.changes.map((c) => (
                <button
                  className="linked-item"
                  key={c.job_id}
                  onClick={() => {
                    select(c.job_id);
                    setDetail(null);
                  }}
                >
                  {c.job_id} · {c.container_id || "cargo in source snapshot"} ·{" "}
                  {c.commitment_id || ""}
                  <span>
                    {c.before} → {c.after}
                  </span>
                </button>
              ))
            ) : (
              <p>No assignment changes.</p>
            )}
            <h4>Constraints still enforced</h4>
            <p className="micro">
              These are current blockers; some clear during simulation through
              predecessor completion or service opening. Holds and failures
              require explicit resolution.
            </p>
            {detail.unresolved.map((j) => (
              <div className="constraint-line" key={j.job_id}>
                <b>{j.job_id}</b>
                <span>{j.reasons.join(" · ")}</span>
              </div>
            ))}
          </section>
        </div>
      )}
    </>
  );
}
function ComparisonChart({ candidates }: { candidates: Candidate[] }) {
  const colors = ["#94a09c", "#177d75", "#d39a43", "#6575a9"];
  const maxTime = Math.max(
    1,
    ...candidates.flatMap((c) => c.curve.map((p) => p.minute)),
  );
  const maxCount = Math.max(
    1,
    ...candidates.flatMap((c) => c.curve.map((p) => p.total)),
  );
  return (
    <>
      <svg
        className="chart"
        viewBox="0 0 850 210"
        role="img"
        aria-label="Simulated on-time completion curves"
      >
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <path d={`M40 ${175 - f * 145}H830`} stroke="#e4e8e3" />
            <text x="13" y={180 - f * 145}>
              {Math.round(f * maxCount)}
            </text>
          </g>
        ))}
        {candidates.map((c, i) => (
          <polyline
            key={c.policy}
            points={c.curve
              .map(
                (p) =>
                  `${40 + (p.minute / maxTime) * 780},${175 - (p.on_time / maxCount) * 145}`,
              )
              .join(" ")}
            fill="none"
            stroke={colors[i]}
            strokeWidth="3"
          />
        ))}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <text key={f} x={40 + f * 780} y="203" textAnchor="middle">
            {Math.round(f * maxTime)} min
          </text>
        ))}
      </svg>
      <div className="chart-legend">
        {candidates.map((c, i) => (
          <span key={c.policy}>
            <i style={{ background: colors[i] }} />
            {c.title}
          </span>
        ))}
      </div>
    </>
  );
}
