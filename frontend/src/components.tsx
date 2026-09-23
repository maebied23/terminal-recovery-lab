import { useState } from "react";
import {
  EntityLink,
  JobReadiness,
  ConnectedWork,
  WorkCard,
} from "./RelationPanels";
import { relatedJobs, jobLabel, journey } from "./relationships";
import {
  ArrowRight,
  Box,
  Link2,
  ShieldCheck,
  X,
  AlertTriangle,
  Ship,
  TrainFront,
  Truck,
  ChevronRight,
} from "lucide-react";
import type { State, Job, Metrics } from "./types";
import { clock } from "./types";
export function Badge({ value }: { value: string }) {
  return (
    <span className={`badge ${value.replaceAll(" ", "-")}`}>
      {value.replaceAll("_", " ")}
    </span>
  );
}
export function MetricStrip({ s }: { s: State }) {
  const m = s.metrics;
  return (
    <div className="metrics">
      <div>
        <span>TRACKED CARGO</span>
        <strong>
          {s.containers.filter((c) => c.location_id || c.job_id).length}
          <small>containers / visits</small>
        </strong>
      </div>
      <div>
        <span>WORK IN MOTION</span>
        <strong>
          {s.jobs.filter((j) => j.status === "running").length}
          <small>active moves</small>
        </strong>
      </div>
      <div>
        <span>COMMITMENTS MET</span>
        <strong>
          {m.on_time}
          <small>/ {m.total} on time</small>
        </strong>
      </div>
      <div>
        <span>NEEDS ATTENTION</span>
        <strong className="amber">
          {s.equipment.filter((e) => e.status === "failed").length +
            s.containers.filter((c) => !c.released).length}
          <small>failures & holds</small>
        </strong>
      </div>
    </div>
  );
}
export function JobTable({
  jobs,
  select,
  selected,
}: {
  jobs: Job[];
  select: (id: string) => void;
  selected: string;
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Move / cargo</th>
            <th>Route</th>
            <th>Assignment</th>
            <th>Cutoff</th>
            <th>State</th>
            <th>Constraint</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr
              key={j.id}
              onClick={() => select(j.container_id)}
              className={selected === j.container_id ? "selected-row" : ""}
            >
              <td>
                <button
                  className="text-button"
                  onClick={(e) => {
                    e.stopPropagation();
                    select(j.id);
                  }}
                >
                  {j.id}
                </button>
                <small>{j.container_id}</small>
                <small>{j.purpose}</small>
              </td>
              <td>
                {j.source_id} <span className="muted">→</span> {j.target_id}
                <small>{j.kind}</small>
              </td>
              <td>
                {j.equipment_id}
                <small>
                  {j.requirements.map((r) => r.capability).join(" + ")}
                </small>
              </td>
              <td className="mono">{clock(j.deadline)}</td>
              <td>
                <Badge value={j.status} />
              </td>
              <td className="constraint">
                {j.status === "completed"
                  ? `Completed ${clock(j.completed_at!)} · history`
                  : j.status === "running"
                    ? "Resources reserved · in progress"
                    : j.blockers?.[0] || "Ready under current constraints"}
                {(j.blockers?.length || 0) > 1 && (
                  <small>+{j.blockers.length - 1} more · inspect</small>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!jobs.length && <div className="empty">No moves match this view.</div>}
    </div>
  );
}
export function Commitments({
  s,
  select,
}: {
  s: State;
  select: (id: string) => void;
}) {
  return (
    <div className="commitment-row">
      {s.commitments.map((co) => {
        const cargos = s.containers.filter((c) => c.commitment_id === co.id),
          done = cargos.filter((c) => c.location_id === co.location_id).length;
        const Icon =
          co.kind === "rail" ? TrainFront : co.kind === "vessel" ? Ship : Truck;
        return (
          <button
            key={co.id}
            className="commitment-card"
            onClick={() => select(co.id)}
          >
            <div>
              <Icon size={16} />
              <b>{co.id}</b>
              <ChevronRight size={14} />
            </div>
            <span>
              {co.status === "departed"
                ? "Window closed"
                : `${clock(co.cutoff)} cutoff`}{" "}
              <strong>
                {done}/{cargos.length}
              </strong>
            </span>
            <div className="progress">
              <i
                style={{
                  width: `${cargos.length ? (done / cargos.length) * 100 : 0}%`,
                }}
              />
            </div>
          </button>
        );
      })}
    </div>
  );
}
export function Inspector({
  s,
  id,
  select,
  close,
  command,
  role,
  onEvidence,
}: {
  s: State;
  id: string;
  select: (id: string) => void;
  close: () => void;
  command: (cmd: Record<string, unknown>) => void;
  role: string;
  onEvidence: () => void;
}) {
  const [trail, setTrail] = useState<string[]>([]);
  const navigate = (next: string) => {
    if (next !== id) {
      setTrail([...trail, id]);
      select(next);
    }
  };
  const cargo = s.containers.find((c) => c.id === id || c.visit_id === id),
    job = s.jobs.find((j) => j.id === id),
    equipment = s.equipment.find((e) => e.id === id),
    co = s.commitments.find((c) => c.id === id);
  const loc = s.locations.find((l) => l.id === (co?.location_id || id));
  const jobs = relatedJobs(s, id);
  const aboard = loc
    ? s.containers
        .filter((c) => c.location_id === loc.id)
        .sort((a, b) => b.tier - a.tier)
    : [];
  const expected = loc
    ? s.containers.filter(
        (c) =>
          c.location_id !== loc.id &&
          s.jobs.some(
            (j) =>
              j.container_id === c.id &&
              j.target_id === loc.id &&
              j.status !== "completed",
          ),
      )
    : [];
  const departed = loc
    ? s.containers.filter(
        (c) =>
          c.location_id !== loc.id &&
          s.jobs.some(
            (j) =>
              j.container_id === c.id &&
              j.source_id === loc.id &&
              j.status === "completed",
          ),
      )
    : [];
  const link = (target: string) => <EntityLink id={target} select={navigate} />;
  const manifest = (label: string, rows: typeof aboard) => (
    <details open={label.startsWith("Currently")}>
      <summary>
        {label} · {rows.length}
      </summary>
      {rows.map((c) => (
        <button className="work-card" key={c.id} onClick={() => navigate(c.id)}>
          <strong>
            {c.id} · {c.flow}
          </strong>
          <span>
            {c.location_id || `In transit on ${c.job_id}`} →{" "}
            {c.commitment_id || "Stored inventory"}
          </span>
        </button>
      ))}
      {!rows.length && <p className="micro">None in this state.</p>}
    </details>
  );
  return (
    <aside className="inspector">
      <div className="inspector-top">
        <span>FOLLOW THE WORK</span>
        <button aria-label="Close inspector" onClick={close}>
          <X size={18} />
        </button>
      </div>
      {trail.length > 0 && (
        <button
          className="text-button"
          onClick={() => {
            select(trail[trail.length - 1]);
            setTrail(trail.slice(0, -1));
          }}
        >
          ← Back to {trail[trail.length - 1]}
        </button>
      )}
      <div className="inspect-title">
        <div>
          <span>
            {cargo
              ? "Container / visit"
              : job
                ? "Handling job"
                : equipment
                  ? "Equipment"
                  : co
                    ? "Service and physical location"
                    : "Location"}
          </span>
          <h2>{id}</h2>
        </div>
      </div>
      <div className="inspector-body">
        <p className="state-caption">
          Simulated observed state · {clock(s.minute)} · r{s.revision}
        </p>
        {cargo && (
          <>
            <dl>
              <dt>Container</dt>
              <dd>{link(cargo.id)}</dd>
              <dt>Visit</dt>
              <dd>{link(cargo.visit_id)}</dd>
              <dt>You are here</dt>
              <dd>{link(cargo.location_id || cargo.job_id || "")}</dd>
              <dt>Commitment</dt>
              <dd>
                {cargo.commitment_id
                  ? link(cargo.commitment_id)
                  : "Stored inventory"}
              </dd>
              <dt>Weight / tier</dt>
              <dd>
                {cargo.weight_t} t / {cargo.tier}
              </dd>
              <dt>Release</dt>
              <dd>
                {cargo.released ? "Released" : cargo.hold_reason || "Held"}
              </dd>
            </dl>
            <h4>Container journey · planned and completed steps</h4>
            {journey(s, cargo.id).map((j) => (
              <WorkCard key={j.id} j={j} select={navigate} />
            ))}
          </>
        )}
        {job && (
          <>
            <h3>{jobLabel(job)}</h3>
            <p className="purpose">{job.purpose}</p>
            <dl>
              <dt>Container</dt>
              <dd>{link(job.container_id)}</dd>
              <dt>Visit</dt>
              <dd>{link(job.visit_id)}</dd>
              <dt>Source</dt>
              <dd>{link(job.source_id)}</dd>
              <dt>Destination</dt>
              <dd>{link(job.target_id)}</dd>
              <dt>Commitment</dt>
              <dd>{job.commitment_id ? link(job.commitment_id) : "Storage"}</dd>
              <dt>Cutoff</dt>
              <dd>{clock(job.deadline)}</dd>
              <dt>Status</dt>
              <dd>
                <Badge value={job.status} />
              </dd>
              <dt>Timing</dt>
              <dd>
                {job.status === "queued"
                  ? `Not started · ${job.duration} min base + transfer estimate`
                  : job.status === "running"
                    ? `${job.remaining} min remaining`
                    : `Completed ${clock(job.completed_at!)}`}
              </dd>
            </dl>
            <JobReadiness j={job} select={navigate} />
            {job.status === "queued" && role !== "reader" && (
              <button
                className="primary full"
                disabled={!!job.blockers.length}
                onClick={() =>
                  command({ action: "dispatch", entity_id: job.id })
                }
              >
                Dispatch {job.container_id}
              </button>
            )}
          </>
        )}
        {equipment && (
          <>
            <dl>
              <dt>Capability / zone</dt>
              <dd>
                {equipment.kind} / {equipment.zone}
              </dd>
              <dt>Availability</dt>
              <dd>{equipment.status}</dd>
              <dt>Reserved on</dt>
              <dd>
                {equipment.job_id
                  ? link(equipment.job_id)
                  : "No active reservation"}
              </dd>
            </dl>
            <p>
              Assignments are plans. Reservations commit this resource to
              running work.
            </p>
            <details>
              <summary>
                Compatible queued work · capability, not assignment
              </summary>
              {s.jobs
                .filter(
                  (j) =>
                    j.status === "queued" &&
                    j.requirements.some((r) =>
                      r.eligible.includes(equipment.id),
                    ),
                )
                .map((j) => (
                  <WorkCard key={j.id} j={j} select={navigate} />
                ))}
            </details>
            {equipment.status === "failed" && (
              <p className="purpose">
                In-flight cargo stays reserved until repair. Queued work may be
                reassigned.
              </p>
            )}
          </>
        )}
        {co && (
          <dl>
            <dt>Open → cutoff</dt>
            <dd>
              {clock(co.arrival)} → {clock(co.cutoff)}
            </dd>
            <dt>Status</dt>
            <dd>{co.status}</dd>
            <dt>Capacity</dt>
            <dd>{co.capacity}</dd>
            <dt>Physical location</dt>
            <dd>{link(co.location_id)}</dd>
          </dl>
        )}
        {loc && (
          <>
            <h4>
              {loc.label} · {aboard.length}/{loc.capacity} occupied
            </h4>
            {manifest(
              loc.kind === "vessel" ? "Currently aboard" : "Currently here",
              aboard,
            )}
            {manifest("Expected arrivals · planned", expected)}
            {manifest("Already handled away · history", departed)}
          </>
        )}
        {!cargo && !job && (
          <ConnectedWork key={id} s={s} id={id} select={navigate} />
        )}
        {co && (
          <details>
            <summary>Outbound committed cargo</summary>
            {s.containers
              .filter((c) => c.commitment_id === co.id)
              .map((c) => (
                <div key={c.id}>
                  {link(c.id)} · {c.location_id || "in transit"}
                </div>
              ))}
          </details>
        )}
        <button className="secondary full" onClick={onEvidence}>
          Trace relationships & evidence <ArrowRight size={15} />
        </button>
        <p className="micro">
          {jobs.length} connected jobs. Source: synthetic simulator.{" "}
          {s.provenance.resource_model === "legacy-v1"
            ? "Legacy resource model: create a fresh shift for coordinated yard handoffs."
            : "Coordinated resources reserved for the whole move."}
        </p>
      </div>
    </aside>
  );
}

export function Score({ m }: { m: Metrics }) {
  return (
    <div className="score-grid">
      <div>
        <strong>{m.on_time}</strong>
        <span>on time</span>
      </div>
      <div>
        <strong>{m.missed}</strong>
        <span>missed</span>
      </div>
      <div>
        <strong>{m.mean_wait}</strong>
        <span>mean wait · min</span>
      </div>
    </div>
  );
}
