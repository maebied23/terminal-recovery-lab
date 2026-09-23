import { equipmentName, cargoName } from "./departure";
import { relatedJobs } from "./relationships";
import { WorkCard } from "./RelationPanels";
import type { InputRecord } from "./types";
import { useState } from "react";
import {
  GitBranch,
  ShieldCheck,
  AlertTriangle,
  Play,
  Download,
} from "lucide-react";
import type { State, Experiment } from "./types";
import { Badge } from "./components";
export function Scenarios({
  s,
  recover,
  role,
  login,
  command,
  fork,
  experiments,
  compare,
  cancel,
  select,
  inputs,
  recordInput,
}: {
  recover: () => void;
  select: (id: string) => void;
  inputs: InputRecord[];
  recordInput: (body: unknown) => Promise<void>;
  s: State;
  role: string;
  login: (code: string) => Promise<void>;
  command: (cmd: Record<string, unknown>) => void;
  fork: (fresh: boolean, profile: string) => void;
  experiments: Experiment[];
  compare: () => void;
  cancel: (id: string) => void;
}) {
  const [code, setCode] = useState(""),
    [equipment, setEquipment] = useState("YC-1"),
    [observed, setObserved] = useState("0"),
    [value, setValue] = useState("available");
  const [source, setSource] = useState("equipment-feed-rehearsal"),
    [sourceId, setSourceId] = useState("event-001"),
    [inputEntity, setInputEntity] = useState("YC-1"),
    [inputMessage, setInputMessage] = useState("");
  const [routeEdge, setRouteEdge] = useState("");
  const [coverTarget, setCoverTarget] = useState("MV-003");
  const affected = relatedJobs(s, equipment).filter(
    (j) => j.status !== "completed",
  );
  const isAdmin = role === "scenario-admin";
  const canDisturb = isAdmin && !!s.parent && !s.running;
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">CONTROLLED EXPERIMENTS</div>
          <h1>Scenario lab</h1>
          <p>
            Fork a shift, inject an explicit disruption, then compare recovery
            outcomes.
          </p>
        </div>
        <Badge value={role} />
      </div>
      <section
        className="panel scenario-guide"
        aria-label="Disruption walkthrough"
      >
        <div>
          <span>1</span>
          <h3>Branch</h3>
          <p>
            {s.parent
              ? `Branch of revision ${s.parent.revision}`
              : "Preserve this shift before testing."}
          </p>
          <button
            disabled={!isAdmin || s.running}
            onClick={() => fork(false, "standard")}
          >
            Fork this shift
          </button>
        </div>
        <div>
          <span>2</span>
          <h3>Disrupt & observe</h3>
          <p>
            Choose equipment below. Failed in-progress loads keep their
            resources.
          </p>
        </div>
        <div>
          <span>3</span>
          <h3>Recover</h3>
          <p>Repair a suspended load, then compare a new schedule.</p>
          <button onClick={recover}>Open recovery</button>
        </div>
      </section>
      {s.movement && (
        <section className="panel">
          <h3>Route availability</h3>
          <p>
            Close a directed road segment on this branch. Existing loads retain
            their holder and recorded progress.
          </p>
          <select
            aria-label="Route segment"
            value={routeEdge}
            onChange={(e) => setRouteEdge(e.target.value)}
          >
            <option value="">Select segment</option>
            {s.movement.edges.map((e) => (
              <option key={e.id} value={e.id}>
                {e.source} → {e.target} · {e.metres} m
                {e.closed ? " · Closed" : ""}
              </option>
            ))}
          </select>
          <button
            disabled={!canDisturb || !routeEdge}
            onClick={() =>
              command({ action: "close_route", entity_id: routeEdge })
            }
          >
            Close segment
          </button>
          <button
            disabled={!canDisturb || !routeEdge}
            onClick={() =>
              command({ action: "open_route", entity_id: routeEdge })
            }
          >
            Reopen segment
          </button>
        </section>
      )}
      {!s.parent && (
        <p className="notice">
          Create a branch to enable disruption controls. Existing shift history
          is preserved.
        </p>
      )}
      {s.running && (
        <p className="notice warning">
          Pause the clock before injecting or repairing a disruption.
        </p>
      )}
      {!isAdmin && (
        <section className="panel admin-panel">
          <ShieldCheck size={25} />
          <div>
            <h3>Scenario controls require an administrator session</h3>
            <p>
              Operator approval does not grant authority to invent observations
              or clear holds. Your local administrator code is in{" "}
              <code>.local/admin-code</code>.
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                login(code)
                  .then(() => setCode(""))
                  .catch(() => {});
              }}
              className="input-row"
            >
              <input
                type="password"
                aria-label="Scenario administrator code"
                placeholder="Local administrator code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
              <button className="primary">Unlock scenario controls</button>
            </form>
          </div>
        </section>
      )}
      <div className="scenario-grid">
        <section className="panel">
          <div className="tile-icon">
            <GitBranch />
          </div>
          <h3>Start from a known state</h3>
          <p>
            Fresh shifts keep prior runs intact. Forks inherit the current
            physical state and record their parent revision.
          </p>
          <div className="button-stack">
            <button
              className="secondary"
              disabled={!isAdmin}
              onClick={() => fork(false, "standard")}
            >
              Create another branch
            </button>
            <button
              className="secondary"
              disabled={!isAdmin}
              onClick={() => fork(true, "standard")}
            >
              New standard shift · 144 containers
            </button>
            <button
              className="secondary"
              disabled={!isAdmin}
              onClick={() => fork(true, "small")}
            >
              New inspection shift · 24 containers
            </button>
          </div>
        </section>
        <section className="panel">
          <div className="tile-icon amber-bg">
            <AlertTriangle />
          </div>
          <h3>Equipment disruption</h3>
          <p>
            Queued work can recover through reassignment. An in-flight load
            stays reserved until its failed equipment is repaired.
          </p>
          <select
            aria-label="Scenario equipment"
            value={equipment}
            onChange={(e) => setEquipment(e.target.value)}
          >
            {s.equipment.map((e) => (
              <option key={e.id} value={e.id}>
                {equipmentName(s, e.id)}
              </option>
            ))}
          </select>
          <p className="micro">
            {
              s.jobs.filter(
                (j) =>
                  j.status === "queued" &&
                  j.requirements.some((r) => r.eligible.includes(equipment)),
              ).length
            }{" "}
            queued jobs could use this capability. These are candidates, not all
            assigned work.
          </p>
          <details>
            <summary>
              Potential impact · {affected.length} assigned or reserved jobs
            </summary>
            {affected.map((j) => (
              <WorkCard key={j.id} j={j} select={select} />
            ))}
            <p>
              Commitments:{" "}
              {Array.from(
                new Set(affected.map((j) => j.commitment_id).filter(Boolean)),
              ).join(", ") || "none"}
              . Unassigned shared resources can also constrain future dispatch.
            </p>
          </details>
          <div className="input-row">
            <button
              className="danger"
              disabled={!canDisturb}
              onClick={() => command({ action: "fail", entity_id: equipment })}
            >
              Inject failure
            </button>
            <button
              className="secondary"
              disabled={!canDisturb}
              onClick={() =>
                command({ action: "repair", entity_id: equipment })
              }
            >
              Repair
            </button>
          </div>
        </section>
        <section className="panel">
          <div className="tile-icon">
            <ShieldCheck />
          </div>
          <h3>Authority feed</h3>
          <p>
            This is a synthetic external authority observation, not a planner
            override of customs or legal release.
          </p>
          {s.containers
            .filter((c) => c.commitment_id && !c.released)
            .map((c) => (
              <div key={c.id} className="release-row">
                <b>{cargoName(c.id)}</b>
                <button
                  className="secondary"
                  disabled={!canDisturb}
                  onClick={() =>
                    command({
                      action: "release",
                      entity_id: c.id,
                      released: true,
                    })
                  }
                >
                  Inject release
                </button>
              </div>
            ))}
          {!s.containers.some((c) => !c.released) && (
            <p className="muted">No held cargo in this shift.</p>
          )}
        </section>
        <section className="panel">
          <div className="eyebrow">TWO CLOCKS</div>
          <h3>A late availability correction</h3>
          <p>
            Use the equipment selector above. Event time can precede recording
            time; previous decisions remain inspectable.
          </p>
          <label>
            Occurred at simulation minute
            <input
              aria-label="Observation valid minute"
              type="number"
              value={observed}
              min="0"
              max={s.minute}
              onChange={(e) => setObserved(e.target.value)}
            />
          </label>
          <select
            aria-label="Corrected equipment availability"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          >
            <option value="available">Available</option>
            <option value="failed">Failed</option>
          </select>
          <button
            className="secondary full"
            disabled={!canDisturb || Number(observed) > s.minute}
            onClick={() =>
              command({
                action: "correct",
                entity_id: equipment,
                valid_minute: Number(observed),
                value,
              })
            }
          >
            Record late observation
          </button>
        </section>
      </div>
      <details className="panel">
        <summary>Additional disturbances & input rehearsal</summary>
        <section>
          <h3>Introduce an unplanned stack obstruction</h3>
          <p>
            In a standard scenario, place accessible stored inventory above an
            active yard pickup. This is a labeled synthetic observation. Then
            open Recovery to generate prerequisite jobs that were not in the
            fixture.
          </p>
          <select
            aria-label="Pickup to obstruct"
            value={coverTarget}
            onChange={(e) => setCoverTarget(e.target.value)}
          >
            {s.jobs
              .filter(
                (j) =>
                  j.status === "queued" &&
                  s.containers.find((c) => c.id === j.container_id)
                    ?.location_id === j.source_id &&
                  s.locations.find((l) => l.id === j.source_id)?.kind ===
                    "yard",
              )
              .map((j) => (
                <option key={j.id} value={j.id}>
                  {j.id} · {j.container_id} at {j.source_id}
                </option>
              ))}
          </select>
          <button
            className="secondary"
            disabled={
              !canDisturb ||
              s.running ||
              !s.jobs.some((j) => j.id === coverTarget && j.status === "queued")
            }
            onClick={() =>
              command({
                action: "obstruct",
                entity_id: s.jobs.find((j) => j.id === coverTarget)
                  ?.container_id,
              })
            }
          >
            Inject synthetic cover
          </button>
        </section>
        <section className="panel">
          <h3>Legacy validation-only rehearsal</h3>
          <p>
            Use the input packs above for observations that change operational
            state. This older form only validates and retains an equipment
            observation with source identity and two clocks. Accepted records do
            not update simulator state. Unknown IDs are quarantined; duplicate
            events are idempotent; conflicting reuse is rejected.
          </p>
          <form
            className="feed-form"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await recordInput({
                  source,
                  source_event_id: sourceId,
                  entity_id: inputEntity,
                  event_time: Number(observed),
                  value,
                });
                setInputMessage(
                  "Recorded. Inspect the input ledger in Evidence.",
                );
              } catch (err) {
                setInputMessage(String(err));
              }
            }}
          >
            <label>
              Source
              <input
                value={source}
                onChange={(e) => setSource(e.target.value)}
                required
              />
            </label>
            <label>
              Source event ID
              <input
                value={sourceId}
                onChange={(e) => setSourceId(e.target.value)}
                required
              />
            </label>
            <label>
              Equipment ID
              <input
                value={inputEntity}
                onChange={(e) => setInputEntity(e.target.value)}
                required
              />
            </label>
            <p>
              Uses occurrence minute ({observed}) and availability ({value})
              selected above.
            </p>
            <button className="secondary" disabled={!isAdmin}>
              Validate and retain input
            </button>
          </form>
          <p role="status">{inputMessage}</p>
          <p className="micro">
            {inputs.length} recent input records. No production feed or physical
            writeback is connected.
          </p>
        </section>
      </details>
      <details className="panel">
        <summary>Legacy policy experiments</summary>
        <div className="section-heading">
          <h3>Experiment history</h3>
          <button
            className="primary"
            disabled={
              s.running ||
              experiments.some((e) => ["running", "queued"].includes(e.status))
            }
            onClick={compare}
          >
            <Play size={15} /> Compare this shift
          </button>
        </div>
        <section className="panel">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Experiment</th>
                  <th>Source revision</th>
                  <th>Matched seeds</th>
                  <th>Status</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {experiments.map((e) => (
                  <tr key={e.id}>
                    <td className="mono">{e.id.slice(0, 8)}</td>
                    <td>r{e.base_revision}</td>
                    <td>{e.manifest.seeds.length} × 4 policies</td>
                    <td>
                      <Badge value={e.status} />
                      {e.status === "running" && ` ${e.progress}%`}
                    </td>
                    <td>
                      {["running", "queued"].includes(e.status) ? (
                        <button
                          className="text-button"
                          onClick={() => cancel(e.id)}
                        >
                          Cancel
                        </button>
                      ) : (
                        <a
                          className="text-button"
                          href={`/api/experiments/${e.id}/export`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <Download size={15} /> Export
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!experiments.length && (
            <p className="muted">
              Run a comparison to create an immutable experiment manifest.
            </p>
          )}
        </section>
      </details>
    </>
  );
}
