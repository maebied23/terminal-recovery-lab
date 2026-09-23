import { useEffect, useState } from "react";
import type { State } from "./types";
import { clock } from "./types";
import {
  cargoName,
  serviceName,
  placeName,
  capabilityName,
  equipmentName,
  readable,
  cargoReadiness,
  taskChain,
} from "./departure";
import type { Diagnosis } from "./Diagnosis";
import { MovementDetail } from "./MovementDetail";
import { CaseMap } from "./CaseMap";
import { ScheduleRecovery, ScheduleTimeline } from "./ScheduleRecovery";
import { Placement } from "./Placement";
import { DepartureWorkspace } from "./DepartureWorkspace";
import "./case-workspace.css";

export function CaseWorkspace({
  s,
  run,
  departure,
  cargoId,
  selected,
  chooseDeparture,
  chooseCargo,
  selectWork,
  request,
  command,
  historical,
  stale,
  diagnosis,
  inspect,
  start,
}: {
  s: State;
  run: string;
  departure: string;
  cargoId: string;
  selected: string;
  chooseDeparture: (id: string) => void;
  chooseCargo: (id: string) => void;
  selectWork: (id: string) => void;
  request: (path: string, body?: unknown) => Promise<any>;
  command: (cmd: Record<string, unknown>) => void;
  historical: boolean;
  stale: boolean;
  diagnosis: Diagnosis | null;
  inspect: (id: string) => void;
  start: () => void;
}) {
  const [stage, setStage] = useState(() => {
      const v = new URLSearchParams(location.search).get("stage");
      return [
        "Situation",
        "Required work",
        "Compare & book",
        "Execution",
      ].includes(v || "")
        ? v!
        : "Situation";
    }),
    [preview, setPreview] = useState<{
      job_id: string;
      destination: string;
    } | null>(null);
  useEffect(() => {
    const u = new URL(location.href);
    u.searchParams.set("stage", stage);
    window.history.replaceState(null, "", u);
  }, [stage]);
  const co = s.commitments.find((c) => c.id === departure) || s.commitments[0];
  const cargo = s.containers.find((c) => c.id === cargoId);
  const chain = taskChain(s, cargoId).jobs;
  const job =
    chain.find((j) => j.id === selected) ||
    chain.find((j) => j.status !== "completed") ||
    chain[0];
  const diagnosed = diagnosis?.manifest.find((r) => r.container_id === cargoId);
  const readiness =
    cargo && co ? cargoReadiness(s, cargo, co.location_id, co.cutoff) : null;
  const chosenLocation = s.locations.find((l) => l.id === selected);
  const disabled = historical || stale;
  useEffect(() => {
    setPreview(null);
  }, [run, s.revision, cargoId]);
  if (!co)
    return <section className="panel">No departures in this shift.</section>;
  const pickJob = (id: string) => selectWork(id); // A prerequisite may belong to another cargo: keep the case.
  const manifest = s.containers.filter((c) => c.commitment_id === co.id);
  const selectedRows =
    s.schedule?.rows.filter((r) => chain.some((j) => j.id === r.job_id)) || [];
  return (
    <section
      className="case-workspace"
      aria-label="Departure decision workspace"
    >
      {s.movement && job && ["Required work", "Execution"].includes(stage) && (
        <MovementDetail s={s} job={job} />
      )}
      <header className="case-heading">
        <div>
          <span className="eyebrow">OPERATIONS</span>
          <h1>{serviceName(co.id)}</h1>
        </div>
        <label>
          Departure
          <select
            aria-label="Departure"
            value={co.id}
            onChange={(e) => chooseDeparture(e.target.value)}
          >
            {s.commitments.map((c) => (
              <option key={c.id} value={c.id}>
                {serviceName(c.id)}
              </option>
            ))}
          </select>
        </label>
      </header>
      <div className="case-facts">
        <div>
          <span>Cutoff</span>
          <b>{clock(co.cutoff)}</b>
        </div>
        <div>
          <span>Observed</span>
          <b>{clock(s.minute)}</b>
        </div>
        <div>
          <span>Clock</span>
          <b>{historical ? "Historical" : s.running ? "Running" : "Paused"}</b>
        </div>
        <div>
          <span>Bookings</span>
          <b>{s.schedule?.status || "Not approved"}</b>
        </div>
        <div>
          <span>Data</span>
          <b>Synthetic · r{s.revision}</b>
        </div>
      </div>
      {stale && (
        <p className="notice warning" role="alert">
          Connection stale. Actions unavailable until state refreshes.
        </p>
      )}
      <nav className="case-stages" aria-label="Decision stages">
        {["Situation", "Required work", "Compare & book", "Execution"].map(
          (name, i) => (
            <button
              key={name}
              aria-current={stage === name ? "step" : undefined}
              onClick={() => setStage(name)}
            >
              <span>{i + 1}</span>
              {name}
            </button>
          ),
        )}
      </nav>
      <div className="case-cargo-picker">
        <label>
          Container
          <select
            aria-label="Case container"
            value={cargoId}
            onChange={(e) => chooseCargo(e.target.value)}
          >
            {manifest.map((c) => (
              <option key={c.id} value={c.id}>
                {cargoName(c.id)} ·{" "}
                {cargoReadiness(s, c, co.location_id, co.cutoff).label}
              </option>
            ))}
          </select>
        </label>
        <span>
          {manifest.length} committed ·{" "}
          {
            manifest.filter(
              (c) =>
                cargoReadiness(s, c, co.location_id, co.cutoff).label ===
                "Delivered on time",
            ).length
          }{" "}
          on time
        </span>
      </div>
      {(stage === "Situation" ||
        stage === "Required work" ||
        stage === "Execution") && (
        <>
          <div className="case-investigation">
            <CaseMap
              s={s}
              jobs={chain}
              selected={job?.id || ""}
              select={pickJob}
              preview={preview}
              mode={
                s.schedule &&
                ["approved", "executing"].includes(s.schedule.status)
                  ? "approved"
                  : "instructions"
              }
            />
            <aside className="case-work-panel">
              <div className="case-finding">
                <span className="eyebrow">SELECTED CARGO</span>
                <h2>{cargoName(cargoId)}</h2>
                <b>
                  {diagnosed?.readiness || readiness?.label || "Needs review"}
                </b>
                <p>
                  {cargo ? placeName(s, cargo.location_id) : "Select cargo"}
                  {cargo?.location_id ? ` · tier ${cargo.tier}` : ""}
                </p>
              </div>
              <h3>Required work</h3>
              <ol className="case-work-list">
                {chain.map((j, i) => (
                  <li key={j.id}>
                    <button
                      onClick={() => pickJob(j.id)}
                      aria-pressed={j.id === job?.id}
                    >
                      <span className="step-number">{i + 1}</span>
                      <div>
                        <b>
                          {j.kind === "rehandle"
                            ? "Relocate"
                            : j.kind === "load"
                              ? "Deliver"
                              : j.kind === "discharge"
                                ? "Discharge"
                                : "Move"}{" "}
                          {cargoName(j.container_id).toLowerCase()}
                        </b>
                        <span>
                          {j.source_id} → {j.target_id}
                        </span>
                        <small>
                          {j.status === "queued"
                            ? j.blockers.length
                              ? "Waiting"
                              : "Ready for scheduling"
                            : j.status}
                        </small>
                      </div>
                    </button>
                  </li>
                ))}
              </ol>
              {chain.length === 0 && (
                <p>No work instruction is linked to this cargo.</p>
              )}
              {chain.length > 0 && (
                <button
                  className="primary full"
                  disabled={disabled}
                  onClick={() => setStage("Compare & book")}
                >
                  Compare & book equipment
                </button>
              )}
            </aside>
          </div>
          {stage === "Situation" && job && (
            <section className="panel case-next">
              <div>
                <h3>
                  Next: {job.kind === "rehandle" ? "relocate" : "move"}{" "}
                  {cargoName(job.container_id).toLowerCase()}
                </h3>
                <p>
                  {job.requirements
                    .map((r) => capabilityName(r.capability))
                    .join(" + ")}{" "}
                  · {job.status}
                </p>
              </div>
              <button
                className="primary"
                onClick={() => setStage("Required work")}
              >
                Inspect required work
              </button>
            </section>
          )}
          {chosenLocation && (
            <section className="panel">
              <h3>{placeName(s, chosenLocation.id)}</h3>
              <p>
                {
                  s.containers.filter(
                    (c) => c.location_id === chosenLocation.id,
                  ).length
                }{" "}
                / {chosenLocation.capacity} occupied ·{" "}
                {
                  s.jobs.filter(
                    (j) =>
                      j.target_id === chosenLocation.id &&
                      j.status === "running",
                  ).length
                }{" "}
                incoming in progress
              </p>
            </section>
          )}
          {job && stage !== "Situation" && (
            <section
              className="panel case-work-detail"
              aria-label="Selected work details"
            >
              <div className="section-heading">
                <h2>
                  {job.kind === "rehandle" ? "Relocate" : "Move"}{" "}
                  {cargoName(job.container_id).toLowerCase()}
                </h2>
                <span>{job.status}</span>
              </div>
              <div className="case-facts">
                <div>
                  <span>From</span>
                  <b>{placeName(s, job.source_id)}</b>
                </div>
                <div>
                  <span>To</span>
                  <b>{placeName(s, job.target_id)}</b>
                </div>
                <div>
                  <span>Must follow</span>
                  <b>
                    {job.dependencies.length
                      ? job.dependencies
                          .map((id) => {
                            const j = s.jobs.find((x) => x.id === id);
                            return j
                              ? `${cargoName(j.container_id)} ${j.kind === "rehandle" ? "relocation" : j.kind}`
                              : id;
                          })
                          .join(", ")
                      : "No predecessor"}
                  </b>
                </div>
              </div>
              <p className="work-purpose">{readable(s, job.purpose)}</p>
              {job.blockers.length > 0 && (
                <ul className="case-blockers">
                  {job.blockers.map((reason) => (
                    <li key={reason}>{readable(s, reason)}</li>
                  ))}
                </ul>
              )}
              <h3>Required equipment</h3>
              <div className="case-resource-grid">
                {job.requirements.map((r, i) => (
                  <div key={`${r.role}-${i}`}>
                    <span>{r.role.replaceAll("_", " ")}</span>
                    <h4>{capabilityName(r.capability)}</h4>
                    <b>
                      {r.reserved.length
                        ? `Occupied: ${r.reserved.map((id) => equipmentName(s, id)).join(", ")}`
                        : s.schedule?.rows.find(
                              (row) => row.job_id === job.id,
                            ) &&
                            ["approved", "executing"].includes(
                              s.schedule.status,
                            )
                          ? "Booked — see execution"
                          : "Not booked"}
                    </b>
                    <small>
                      {r.available.length} available now / {r.eligible.length}{" "}
                      compatible
                    </small>
                  </div>
                ))}
              </div>
              <details>
                <summary>Supporting evidence</summary>
                <div className="case-facts">
                  <div>
                    <span>Instruction</span>
                    <b>{job.id}</b>
                  </div>
                  <div>
                    <span>Visit</span>
                    <b>{job.visit_id}</b>
                  </div>
                  <div>
                    <span>Known at</span>
                    <b>Revision {s.revision}</b>
                  </div>
                </div>
                <ul>
                  {job.predecessors.map((p) => (
                    <li key={p.id}>
                      {readable(s, p.reason)} · {p.origin}
                    </li>
                  ))}
                </ul>
                {s.input_provenance?.[
                  `${job.container_id}/container.position`
                ] && (
                  <p>
                    Position source:{" "}
                    {
                      s.input_provenance[
                        `${job.container_id}/container.position`
                      ].source
                    }{" "}
                    · observed{" "}
                    {clock(
                      s.input_provenance[
                        `${job.container_id}/container.position`
                      ].observed_minute,
                    )}{" "}
                    · received{" "}
                    {clock(
                      s.input_provenance[
                        `${job.container_id}/container.position`
                      ].received_minute,
                    )}
                  </p>
                )}
                <button onClick={() => inspect(job.id)}>
                  Open full evidence
                </button>
              </details>
            </section>
          )}
          {stage === "Required work" &&
            job?.kind === "rehandle" &&
            !historical &&
            !stale && (
              <Placement
                key={`${run}-${job.id}`}
                s={s}
                job={job}
                run={run}
                request={request}
                command={command}
                preview={setPreview}
              />
            )}
        </>
      )}
      <div hidden={stage !== "Compare & book"}>
        {!historical && !stale ? (
          <ScheduleRecovery
            s={s}
            run={run}
            departure={co.id}
            request={request}
            command={command}
            select={pickJob}
            caseJobs={chain.map((j) => j.id)}
            selectedJob={
              s.jobs.some((j) => j.id === selected) ? selected : job?.id
            }
          />
        ) : (
          <p className="notice">
            Return to fresh current state before comparing or booking work.
          </p>
        )}
      </div>
      {stage === "Execution" && (
        <section className="panel">
          <div className="section-heading">
            <h2>Execution</h2>
            <div className="input-row">
              <button
                disabled={disabled}
                onClick={() => command({ action: "pause" })}
              >
                Pause
              </button>
              <button
                disabled={disabled || s.running}
                onClick={() => command({ action: "advance", minutes: 1 })}
              >
                Step 1 minute
              </button>
              <button
                disabled={
                  disabled || s.running || s.schedule?.status === "interrupted"
                }
                onClick={() =>
                  command({ action: "clock", running: true, speed: 1 })
                }
              >
                Run
              </button>
            </div>
          </div>
          {s.schedule ? (
            <>
              <p
                className={
                  s.schedule.status === "interrupted" ? "notice warning" : ""
                }
              >
                {s.schedule.reason ||
                  `${s.schedule.status} · ${selectedRows.filter((r) => s.jobs.find((j) => j.id === r.job_id)?.status === "completed").length}/${selectedRows.length} selected booked moves completed`}
              </p>
              <ScheduleTimeline
                s={s}
                mode="approved"
                rows={s.schedule.rows}
                start={Math.min(
                  s.minute,
                  ...s.schedule.rows.map((r) => r.start),
                )}
                end={s.schedule.end_minute}
                select={pickJob}
                selectedJob={
                  s.jobs.some((j) => j.id === selected) ? selected : job?.id
                }
                departure={co.id}
              />
            </>
          ) : (
            <p>
              No approved schedule. Compare and book equipment before running a
              controlled recovery.
            </p>
          )}
          <button onClick={() => setStage("Compare & book")}>
            Inspect bookings & outcomes
          </button>
        </section>
      )}
      <details className="case-reference">
        <summary>Detailed inventory & model inspection</summary>
        <DepartureWorkspace
          s={s}
          commitmentId={co.id}
          setCommitment={chooseDeparture}
          selected={cargoId}
          select={chooseCargo}
          historical={historical}
          stale={stale}
          inspect={inspect}
          recovery={() => setStage("Compare & book")}
          start={start}
          diagnosis={diagnosis}
          navigate={() => setStage("Compare & book")}
          inspectDiagnosis={inspect}
        />
      </details>
    </section>
  );
}
