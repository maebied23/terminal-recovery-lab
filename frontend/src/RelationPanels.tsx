import { useState } from "react";
import type { State, Job } from "./types";
import { clock } from "./types";
import { relatedJobs, jobLabel } from "./relationships";
export function EntityLink({
  id,
  select,
}: {
  id: string;
  select: (id: string) => void;
}) {
  return (
    <button className="text-button" onClick={() => select(id)}>
      {id}
    </button>
  );
}
export function WorkCard({
  j,
  select,
}: {
  j: Job;
  select: (id: string) => void;
}) {
  return (
    <button className={`work-card ${j.status}`} onClick={() => select(j.id)}>
      <strong>{jobLabel(j)}</strong>
      <span>
        {j.source_id} → {j.target_id}
      </span>
      <small>
        {j.status === "completed"
          ? `Completed ${j.completed_at === null ? "" : clock(j.completed_at)} · recorded history`
          : j.status === "running"
            ? `In progress · ${j.remaining} min remaining`
            : j.blockers[0] || "Ready to dispatch"}
      </small>
    </button>
  );
}
export function JobReadiness({
  j,
  select,
}: {
  j: Job;
  select: (id: string) => void;
}) {
  return (
    <>
      <h4>Required resources</h4>
      {j.requirements.map((r) => (
        <div className="readiness-item" key={r.role}>
          <b>
            {r.role} · {r.capability}
          </b>
          <span>
            Assigned:{" "}
            {r.assigned ? (
              <EntityLink id={r.assigned} select={select} />
            ) : (
              "allocate at dispatch"
            )}
          </span>
          <span>
            {j.status === "completed" ? "Used" : "Reserved"}:{" "}
            {(j.status === "completed"
              ? j.resources.filter((e) => r.eligible.includes(e))
              : r.reserved
            ).map((e) => (
              <EntityLink key={e} id={e} select={select} />
            ))}
            {j.status !== "completed" &&
              !r.reserved.length &&
              "not yet reserved"}
          </span>
          {j.status === "queued" && (
            <small>
              Free compatible resources: {r.available.join(", ") || "none"}
            </small>
          )}
        </div>
      ))}
      <h4>Readiness</h4>
      {j.status === "completed" ? (
        <p>
          Finished at{" "}
          {j.completed_at === null ? "recorded time" : clock(j.completed_at)}.
          These are historical assignments, not pending work.
        </p>
      ) : j.blockers.length ? (
        <ul className="reason-list">
          {j.blockers.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      ) : (
        <p>
          {j.status === "running"
            ? "Resources reserved; movement in progress."
            : "All currently modeled dispatch checks pass."}
        </p>
      )}
      <h4>Must happen first</h4>
      {j.predecessors.length ? (
        j.predecessors.map((d) => (
          <div className="readiness-item" key={d.id}>
            <EntityLink id={d.id} select={select} />
            <span>{d.reason}</span>
            <small>
              {d.kind} · {d.origin} · basis r{d.basis_revision}
            </small>
          </div>
        ))
      ) : (
        <p>No predecessor jobs. Other readiness checks still apply.</p>
      )}
      <h4>Enables next</h4>
      {j.successors.length ? (
        j.successors.map((id) => (
          <EntityLink key={id} id={id} select={select} />
        ))
      ) : (
        <p>No recorded successor jobs.</p>
      )}
      <details>
        <summary>Physical stages and model limits</summary>
        {j.stages.map((stage) => (
          <p key={stage.name}>
            <b>{stage.name}</b> · {stage.location}
            <br />
            {stage.capability}
          </p>
        ))}
        <p className="micro">
          Stages explain the handling contract; they are not independent
          equipment telemetry. Resources are reserved together for the whole
          move. Rail/road handoffs remain abstract.
        </p>
      </details>
    </>
  );
}
export function RelationshipLens({
  s,
  id,
  select,
}: {
  s: State;
  id: string;
  select: (id: string) => void;
}) {
  const edges = s.relationships.edges.filter(
    (e) => e.source === id || e.target === id,
  );
  return (
    <div className="relationship-list">
      {edges.map((e, i) => (
        <div key={i}>
          <EntityLink id={e.source} select={select} />
          <span>{e.relation}</span>
          <EntityLink id={e.target} select={select} />
          <small>
            {e.reason || e.state}
            {s.jobs.find((j) => j.id === e.source)?.status === "completed"
              ? " · completed job history"
              : ""}
          </small>
        </div>
      ))}
      {!edges.length && (
        <p>Select an operational object to inspect its relationships.</p>
      )}
    </div>
  );
}
export function ConnectedWork({
  s,
  id,
  select,
}: {
  s: State;
  id: string;
  select: (id: string) => void;
}) {
  const [show, setShow] = useState(false);
  const jobs = relatedJobs(s, id),
    pending = jobs.filter((j) => j.status !== "completed"),
    done = jobs.filter((j) => j.status === "completed");
  return (
    <>
      <h4>Current work · {pending.length}</h4>
      {pending.length ? (
        pending.map((j) => <WorkCard key={j.id} j={j} select={select} />)
      ) : (
        <p>No outstanding work in this selection.</p>
      )}
      <button className="text-button" onClick={() => setShow(!show)}>
        {show ? "Hide" : "Show"} completed history · {done.length}
      </button>
      {show && done.map((j) => <WorkCard key={j.id} j={j} select={select} />)}
    </>
  );
}
