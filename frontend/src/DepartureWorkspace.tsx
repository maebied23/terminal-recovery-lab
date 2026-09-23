import { useState } from "react";
import type { State, Job } from "./types";
import { clock } from "./types";
import { TerminalMap } from "./Map";
import { actionName } from "./relationships";
import {
  cargoName,
  serviceName,
  equipmentName,
  capabilityName,
  placeName,
  readable,
  cargoReadiness,
  equipmentActivity,
} from "./departure";
import "./departure.css";
import { DiagnosisPanel } from "./Diagnosis";
import type { Diagnosis, Workspace } from "./Diagnosis";

export function DepartureWorkspace({
  s,
  commitmentId,
  setCommitment,
  selected,
  select,
  historical,
  stale,
  inspect,
  recovery,
  start,
  diagnosis,
  navigate,
  inspectDiagnosis,
}: {
  diagnosis?: Diagnosis | null;
  navigate: (page: Workspace) => void;
  inspectDiagnosis: (id: string) => void;
  s: State;
  commitmentId: string;
  setCommitment: (id: string) => void;
  selected: string;
  select: (id: string) => void;
  historical: boolean;
  stale: boolean;
  inspect: (id: string) => void;
  recovery: (id: string) => void;
  start: () => void;
}) {
  const [view, setView] = useState("Stack & access");
  const co =
    s.commitments.find((c) => c.id === commitmentId) || s.commitments[0];
  if (!co) return <div className="panel">No departures in this shift.</div>;
  const manifest = s.containers
    .filter((c) => c.commitment_id === co.id)
    .map((cargo) => {
      const local = cargoReadiness(s, cargo, co.location_id, co.cutoff);
      const diagnosed = diagnosis?.manifest.find(
        (r) => r.container_id === cargo.id,
      );
      return {
        cargo,
        ...local,
        ...(diagnosed
          ? {
              label: diagnosed.readiness,
              next: s.jobs.find((j) => j.id === diagnosed.next_job_id) || null,
            }
          : {}),
      };
    });
  const selectedCargo =
    s.jobs.find((j) => j.id === selected)?.container_id || selected;
  const chosen =
    manifest.find((row) => row.cargo.id === selectedCargo) ||
    manifest.find((row) => row.label === "Waiting / blocked") ||
    manifest.find((row) => row.next) ||
    manifest[0];
  const counts = (labels: string[]) =>
    manifest.filter((r) => labels.includes(r.label)).length;
  const delivered = counts(["Delivered on time", "Delivered late"]);
  const incomplete = manifest.length - delivered;
  const remaining = co.cutoff - s.minute;
  const focus = chosen?.next;
  const cargo = chosen?.cargo;
  const stack =
    cargo &&
    s.locations.find((l) => l.id === cargo.location_id && l.kind === "yard");
  const occupants = stack
    ? s.containers
        .filter((c) => c.location_id === stack.id)
        .sort((a, b) => b.tier - a.tier)
    : [];
  const covers = cargo ? occupants.filter((c) => c.tier > cargo.tier) : [];
  const stateText = historical
    ? "Historical snapshot"
    : "Current simulated observations";
  return (
    <section className="departure" aria-label="Departure workspace">
      {s.dataset && (
        <div className="departure-input-origin">
          <b>Input pack: {s.dataset.title}</b> · Synthetic dataset imported from
          versioned files.{" "}
          <button
            className="text-button"
            onClick={() => inspect(cargo?.id || "YC-1")}
          >
            Inspect input provenance
          </button>
          {cargo && s.input_provenance?.[`${cargo.id}/container.position`] && (
            <p>
              Latest position source:{" "}
              {s.input_provenance[`${cargo.id}/container.position`].source} ·
              observed{" "}
              {clock(
                s.input_provenance[`${cargo.id}/container.position`]
                  .observed_minute,
              )}{" "}
              · delivered{" "}
              {clock(
                s.input_provenance[`${cargo.id}/container.position`]
                  .received_minute,
              )}{" "}
              · known at revision{" "}
              {
                s.input_provenance[`${cargo.id}/container.position`]
                  .known_revision
              }
            </p>
          )}
        </div>
      )}
      <header className="departure-heading">
        <div>
          <div className="eyebrow">DEPARTURE WORKSPACE</div>
          <h1>Protect the next departure.</h1>
          {!diagnosis && (
            <p>
              Follow the cargo, understand the work, then review your options.
            </p>
          )}
        </div>
        {diagnosis ? (
          <button onClick={start}>Inspect starting snapshot · read-only</button>
        ) : (
          <label>
            Departure
            <select
              aria-label="Departure"
              value={co.id}
              onChange={(e) => {
                setCommitment(e.target.value);
                select("");
              }}
            >
              {s.commitments.map((c) => (
                <option value={c.id} key={c.id}>
                  {serviceName(c.id)} · {clock(c.cutoff)}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>
      {!diagnosis && (
        <>
          <div className="departure-banner">
            <div>
              <h2>
                {serviceName(co.id)} <span>Cutoff {clock(co.cutoff)}</span>
              </h2>
              <p>
                {remaining >= 0
                  ? `${remaining} simulated minutes to cutoff`
                  : `Cutoff passed ${-remaining} simulated minutes ago`}{" "}
                · Service {co.status}
              </p>
            </div>
            <div className="departure-source">
              <b>{stateText}</b>
              <span>
                {clock(s.minute)} · revision {s.revision} ·{" "}
                {stale && !historical
                  ? "Connection stale — refresh before deciding"
                  : "Synthetic data; no terminal feed"}
              </span>
              <button onClick={start}>
                Inspect starting snapshot · read-only
              </button>
            </div>
          </div>
          <div
            className="departure-summary"
            aria-label="Cargo readiness totals"
          >
            <div>
              <strong>{manifest.length}</strong>
              <span>Committed containers</span>
            </div>
            <div>
              <strong>{counts(["Delivered on time"])}</strong>
              <span>Delivered on time</span>
            </div>
            <div>
              <strong>{counts(["Next move ready"])}</strong>
              <span>Next move ready</span>
            </div>
            <div>
              <strong>{counts(["Work underway"])}</strong>
              <span>Work underway</span>
            </div>
            <div>
              <strong>
                {counts([
                  "Waiting / blocked",
                  "Work interrupted",
                  "Cutoff missed",
                  "Needs review",
                  "Delivered late",
                ])}
              </strong>
              <span>Needs attention / late</span>
            </div>
          </div>
          <div className="departure-attention" role="status">
            <b>
              {incomplete
                ? `${incomplete} containers still need delivery.`
                : manifest.length
                  ? "All committed cargo has been delivered."
                  : "No cargo is assigned to this departure."}
            </b>{" "}
            {incomplete
              ? "Start with a container below. A ready move does not guarantee an on-time departure."
              : "Check delivery times and the recorded outcome; completed work is history."}
          </div>
        </>
      )}
      <div className="departure-grid">
        <section
          className="departure-panel departure-manifest"
          aria-label="Departure cargo manifest"
        >
          <h3>1 · Choose the cargo</h3>
          <p>All committed cargo, including completed work.</p>
          {manifest.map((row) => (
            <button
              key={row.cargo.id}
              className={`cargo-choice ${row.cargo.id === cargo?.id ? "chosen" : ""}`}
              aria-pressed={row.cargo.id === cargo?.id}
              onClick={() => select(row.cargo.id)}
            >
              <span>
                <b>{cargoName(row.cargo.id)}</b>
                <small>{row.cargo.id} · synthetic identity</small>
              </span>
              <span className="readiness-label">{row.label}</span>
              <span>{placeName(s, row.cargo.location_id)}</span>
            </button>
          ))}
          <p className="departure-note">
            These are existing synthetic IDs, not real shipping-container
            numbers. “Delivered” means its final handling move completed, not
            that the train or vessel has departed.
          </p>
        </section>
        <div className="departure-detail">
          {chosen && cargo ? (
            <>
              {diagnosis && (
                <DiagnosisPanel
                  s={s}
                  report={diagnosis}
                  row={diagnosis.manifest.find(
                    (r) => r.container_id === cargo.id,
                  )}
                  navigate={navigate}
                  inspect={inspectDiagnosis}
                  historical={historical}
                />
              )}
              <section className="departure-panel departure-focus">
                <div className="departure-section-title">
                  <div>
                    <h3>{cargoName(cargo.id)}</h3>
                    <p>
                      {placeName(s, cargo.location_id)} · {cargo.weight_t} t ·{" "}
                      {cargo.released
                        ? "Released"
                        : `On hold: ${cargo.hold_reason || "reason not recorded"}`}
                    </p>
                  </div>
                  <span className="readiness-label">{chosen.label}</span>
                </div>
                <div
                  className="departure-tabs"
                  role="group"
                  aria-label="Cargo views"
                >
                  {["Stack & access", "Terminal map", "Equipment activity"].map(
                    (tab) => (
                      <button
                        key={tab}
                        aria-pressed={view === tab}
                        className={view === tab ? "active" : ""}
                        onClick={() => setView(tab)}
                      >
                        {tab}
                      </button>
                    ),
                  )}
                </div>
                {view === "Stack & access" && (
                  <div className="departure-access">
                    <div>
                      <h4>Physical position</h4>
                      {stack ? (
                        <>
                          <p>
                            {placeName(s, stack.id)} · {occupants.length}/
                            {stack.capacity} positions occupied
                          </p>
                          <div
                            className="stack-section"
                            aria-label="Stack cross-section"
                          >
                            {occupants.map((c) => (
                              <div
                                key={c.id}
                                className={`stack-tier ${c.id === cargo.id ? "selected-tier" : c.tier > cargo.tier ? "cover-tier" : ""}`}
                              >
                                <span>Level {c.tier + 1}</span>
                                <b>{cargoName(c.id)}</b>
                                <small>
                                  {c.id === cargo.id
                                    ? "Selected cargo"
                                    : c.tier > cargo.tier
                                      ? "Above selected cargo"
                                      : "Below selected cargo"}
                                </small>
                              </div>
                            ))}
                          </div>
                          <p className="departure-note">
                            Top shown first. Levels display the stored tier + 1.{" "}
                            {covers.length
                              ? `${covers.length} container(s) are above the selected cargo.`
                              : "No container is above the selected cargo."}
                          </p>
                        </>
                      ) : (
                        <p>
                          {cargo.location_id
                            ? `Cargo is at ${placeName(s, cargo.location_id)}; it is not currently in a yard stack.`
                            : "Cargo is in transit. Its next location is not an observed arrival yet."}
                        </p>
                      )}
                    </div>
                    <div>
                      <h4>What needs to happen next?</h4>
                      {focus ? (
                        <>
                          <b>
                            {actionName(focus)} {cargoName(focus.container_id)}
                          </b>
                          <p>
                            {placeName(s, focus.source_id)} →{" "}
                            {placeName(s, focus.target_id)}
                          </p>
                          {focus.container_id !== cargo.id && (
                            <p className="access-explanation">
                              This move handles another container first because
                              it is a prerequisite for the selected cargo.
                            </p>
                          )}
                          <h4>Current checks</h4>
                          {focus.blockers.length ? (
                            <ul>
                              {focus.blockers.map((reason) => (
                                <li key={reason}>{readable(s, reason)}</li>
                              ))}
                            </ul>
                          ) : (
                            <p>
                              {focus.status === "running"
                                ? "Work is underway. Completion still needs a simulator observation."
                                : "No current dispatch blocker recorded. This move can be considered at the next simulation step."}
                            </p>
                          )}
                        </>
                      ) : (
                        <p>
                          {chosen.label.startsWith("Delivered")
                            ? "No remaining delivery work. The sequence below records completed handling."
                            : "No complete delivery route is recorded. Review the work data before deciding."}
                        </p>
                      )}
                      {chosen.chain.issues.map((issue) => (
                        <p role="alert" key={issue}>
                          {issue}
                        </p>
                      ))}
                    </div>
                  </div>
                )}
                {view === "Terminal map" && (
                  <>
                    <p className="departure-note">
                      Selected cargo and its related work are highlighted. Use
                      the manifest to switch cargo; use Terminal overview to
                      inspect other map objects.
                    </p>
                    <TerminalMap
                      s={s}
                      selected={cargo.id}
                      select={(id) => {
                        const match = manifest.find((r) => r.cargo.id === id);
                        if (match) select(id);
                        else inspect(id);
                      }}
                      flow="all"
                    />
                  </>
                )}
                {view === "Equipment activity" && (
                  <EquipmentActivity s={s} jobs={chosen.chain.jobs} />
                )}
              </section>
              <section className="departure-panel">
                <div className="departure-section-title">
                  <div>
                    <h3>2 · Follow the required work</h3>
                    <p>
                      Dependency order, including work on other containers. This
                      is not a time booking.
                    </p>
                  </div>
                </div>
                <ol className="departure-tasks">
                  {chosen.chain.jobs.map((job, index) => (
                    <Task
                      key={job.id}
                      s={s}
                      job={job}
                      number={index + 1}
                      selectedCargo={cargo.id}
                    />
                  ))}
                </ol>
              </section>
              <section className="departure-panel departure-next">
                <div>
                  <h3>3 · Review the decision</h3>
                  <p>
                    {historical
                      ? "You are inspecting history. Return to current state before comparing or changing work."
                      : incomplete
                        ? "Existing recovery tools can compare whole-shift policies or propose access work. They do not yet book future equipment time, and a policy may affect other departures."
                        : "This departure has no remaining delivery work. Inspect its evidence or select another departure."}
                  </p>
                </div>
                <div className="departure-actions">
                  <button
                    className="secondary"
                    onClick={() => inspect(cargo.id)}
                  >
                    Inspect cargo evidence
                  </button>
                  <button
                    className="primary"
                    disabled={historical || stale || !incomplete || !focus}
                    onClick={() => recovery(focus?.id || cargo.id)}
                  >
                    Open existing recovery tools
                  </button>
                </div>
              </section>
            </>
          ) : (
            <div className="departure-panel">
              No committed cargo to inspect.
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function Task({
  s,
  job,
  number,
  selectedCargo,
}: {
  s: State;
  job: Job;
  number: number;
  selectedCargo: string;
}) {
  return (
    <li className={`departure-task ${job.status}`}>
      <div className="task-number">{number}</div>
      <div className="task-body">
        <div className="departure-section-title">
          <b>
            {actionName(job)} {cargoName(job.container_id)}
          </b>
          <span className="readiness-label">
            {job.status === "queued" ? "Queued · no booked time" : job.status}
          </span>
        </div>
        <p>
          {placeName(s, job.source_id)} → {placeName(s, job.target_id)}
        </p>
        {job.container_id !== selectedCargo && (
          <p className="departure-note">
            Prerequisite work on another container.
          </p>
        )}
        {job.predecessors.map((dep) => (
          <p className="dependency-reason" key={dep.id}>
            After {readable(s, dep.id)}: {readable(s, dep.reason)}
          </p>
        ))}
        <div className="task-requirements">
          {job.requirements.map((req, i) => (
            <div key={`${req.role}-${i}`}>
              <b>{capabilityName(req.capability)}</b>
              <span>{req.role}</span>
              <span>
                {job.status === "completed"
                  ? `Used: ${
                      job.resources
                        .filter((id) => req.eligible.includes(id))
                        .map((id) => equipmentName(s, id))
                        .join(", ") || "Not recorded"
                    }`
                  : req.reserved.length
                    ? `In use: ${req.reserved.map((id) => equipmentName(s, id)).join(", ")}`
                    : req.assigned
                      ? `Assigned: ${equipmentName(s, req.assigned)} · not reserved`
                      : "Assigned at dispatch · not reserved"}
              </span>
              {job.status === "queued" && (
                <small>
                  Available compatible pool:{" "}
                  {req.available.map((id) => equipmentName(s, id)).join(", ") ||
                    "None now"}
                  . Full dispatch checks still apply.
                </small>
              )}
            </div>
          ))}
        </div>
        <details>
          <summary>Move reference, timing and checks</summary>
          <p>
            {job.id} · {job.container_id} · {job.visit_id}
          </p>
          <p>
            Started:{" "}
            {job.started_at === null ? "Not started" : clock(job.started_at)} ·
            Completed:{" "}
            {job.completed_at === null
              ? "Not completed"
              : clock(job.completed_at)}
          </p>
          <p>
            Base handling assumption: {job.duration} min. No completion forecast
            or future reservation is implied.
          </p>
          {job.status !== "completed" &&
            job.blockers.map((reason) => (
              <p key={reason}>{readable(s, reason)}</p>
            ))}
        </details>
      </div>
    </li>
  );
}

function EquipmentActivity({ s, jobs }: { s: State; jobs: Job[] }) {
  const relevant = new Set(
    jobs.flatMap((j) => [
      j.equipment_id,
      ...j.resources,
      ...j.requirements.flatMap((r) => r.eligible),
    ]),
  );
  const max = Math.max(1, s.minute);
  return (
    <div className="equipment-activity">
      <h4>
        Recorded equipment activity · {clock(0)}–{clock(s.minute)}
      </h4>
      <p>
        Solid bars show elapsed use, including other departures. Running work
        ends at the snapshot clock. Queued work has no start/end booking.
      </p>
      <div className="activity-axis">
        <span>{clock(0)}</span>
        <span>{clock(s.minute)} · observation</span>
      </div>
      {s.equipment
        .filter((e) => relevant.has(e.id))
        .map((e) => {
          const activity = equipmentActivity(s, e.id);
          const queued = s.jobs.filter(
            (j) => j.status === "queued" && j.equipment_id === e.id,
          );
          return (
            <div className="activity-row" key={e.id}>
              <div>
                <b>{equipmentName(s, e.id)}</b>
                <small>
                  {e.status === "failed"
                    ? "Unavailable"
                    : e.job_id
                      ? "In use"
                      : e.within_shift === false
                        ? "Outside shift"
                        : "Available now"}{" "}
                  · {e.id}
                </small>
              </div>
              <div>
                <div
                  className="activity-track"
                  aria-label={`${equipmentName(s, e.id)} elapsed use`}
                >
                  {activity.map((a) => (
                    <span
                      key={`${a.job.id}:${a.start}`}
                      className={a.active ? "activity-running" : ""}
                      style={{
                        left: `${(a.start / max) * 100}%`,
                        width: `${Math.max(0.5, ((a.end - a.start) / max) * 100)}%`,
                      }}
                      title={`${cargoName(a.job.container_id)}: ${clock(a.start)}–${clock(a.end)} (${a.job.status})`}
                    />
                  ))}
                </div>
                <small>
                  {activity.length
                    ? activity
                        .map(
                          (a) =>
                            `${cargoName(a.job.container_id)} ${clock(a.start)}–${clock(a.end)}${a.active ? " (ongoing)" : ""}`,
                        )
                        .join("; ")
                    : "No recorded activity"}
                </small>
                <p className="departure-note">
                  {queued.length} queued primary assignment(s), unscheduled.{" "}
                  {e.kind === "tractor"
                    ? "Transport is allocated at dispatch."
                    : ""}
                </p>
              </div>
            </div>
          );
        })}
      <p className="departure-note">
        Availability now is not a future booking guarantee. The current engine
        reserves resources for a whole move; stage-level scheduling comes later.
      </p>
    </div>
  );
}
