import { useEffect, useState, useRef } from "react";
import { clock } from "./types";
import type { State, Job } from "./types";
import { cargoName, serviceName } from "./departure";
type Option = {
  capacity: number;
  occupancy?: {
    at_minute: number;
    until_minute: number;
    occupied: number;
    capacity: number;
    free_slots: number;
  }[];
  movement?: { start: number; end: number };
  destination: string;
  prescribed: boolean;
  free_slots: number;
  occupied: number;
  incoming: number;
  immediate_distance: number;
  onward_distance: number;
  excluded_reason: string | null;
  validation: string;
  error?: string;
  metrics?: { missed: number; lateness: number };
  impact?: {
    id: string;
    delta: number | null;
    on_time: number;
    total: number;
  }[];
  changes?: { job_id: string; field: string; before: string; after: string }[];
};
type Proposal = {
  id: string;
  base_revision: number;
  recommended: string | null;
  prescribed: string;
  facts: Option[];
  candidates: Option[];
  assumptions: string[];
};
export function Placement({
  s,
  job,
  run,
  request,
  command,
  preview,
}: {
  s: State;
  job: Job;
  run: string;
  request: (path: string, body?: unknown) => Promise<any>;
  command: (c: Record<string, unknown>) => void;
  preview: (x: { job_id: string; destination: string } | null) => void;
}) {
  const liveRequest = useRef(0);
  const [result, setResult] = useState<Proposal | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [destination, setDestination] = useState(""),
    [confirm, setConfirm] = useState(false);
  useEffect(() => {
    let live = true;
    liveRequest.current++;
    setResult(null);
    setError("");
    setConfirm(false);
    setDestination("");
    preview(null);
    request(
      `/api/placements?run=${encodeURIComponent(run)}&job_id=${encodeURIComponent(job.id)}`,
    )
      .then((rows) => {
        if (live) setResult(rows[0]?.result || null);
      })
      .catch((e) => {
        if (live) setError(String(e));
      });
    return () => {
      live = false;
      liveRequest.current++;
      preview(null);
    };
  }, [run, job.id, request]);
  const stale = result?.base_revision !== s.revision,
    selected = result?.candidates.find((c) => c.destination === destination);
  const best = result?.candidates.find(
    (c) => c.destination === result.recommended,
  );
  const baseline = result?.candidates.find(
    (c) => c.prescribed && c.validation === "passed",
  );
  const reason =
    best?.metrics && baseline?.metrics
      ? best.prescribed
        ? "No tested alternative ranked above the existing destination."
        : best.metrics.missed < baseline.metrics.missed
          ? `${baseline.metrics.missed - best.metrics.missed} fewer cargo misses than the current destination in this model.`
          : best.metrics.lateness < baseline.metrics.lateness
            ? `Lower total modeled lateness with the same missed-cargo count.`
            : `Missed-cargo count and total lateness are unchanged; the ranking then considers relocation work and combined storage/onward distance. Review individual departure impacts below.`
      : "Compare feasible options and their effects on every departure.";
  const blocked = s.running || !!s.schedule || job.status !== "queued";
  async function compare() {
    const token = ++liveRequest.current;
    setBusy(true);
    setError("");
    try {
      const r = await request(
        `/api/placements?run=${encodeURIComponent(run)}`,
        { job_id: job.id, expected_revision: s.revision },
      );
      if (token !== liveRequest.current) return;
      setResult(r);
      setDestination("");
      preview(null);
    } catch (e) {
      if (token === liveRequest.current) setError(String(e));
    } finally {
      if (token === liveRequest.current) setBusy(false);
    }
  }
  return (
    <section className="placement panel" aria-label="Placement decision">
      <div className="section-heading">
        <div>
          <h3>Relocation destination</h3>
          <p>
            {cargoName(job.container_id)} · instructed to {job.target_id}
          </p>
          <small>
            {job.placement_basis
              ? `Planner-approved destination · comparison r${job.placement_basis.revision}`
              : "Prescribed by the work instruction; alternatives not yet applied."}
          </small>
        </div>
        <button disabled={blocked || busy} onClick={compare}>
          {busy ? "Checking destinations…" : "Compare destinations"}
        </button>
      </div>
      {blocked && (
        <p className="notice">
          Pause and release the schedule contract before revising queued work.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {result && (
        <>
          <p className={stale ? "notice warning" : "micro"}>
            {stale
              ? "State changed — compare again before applying."
              : `Basis r${result.base_revision} · best validated destination: ${result.recommended || "none"}`}
          </p>
          <p>{reason}</p>
          <div className="placement-options">
            {result.candidates.map((c) => (
              <button
                key={c.destination}
                aria-pressed={destination === c.destination}
                className={destination === c.destination ? "selected" : ""}
                onClick={() => {
                  setDestination(c.destination);
                  setConfirm(false);
                  preview(
                    stale
                      ? null
                      : { job_id: job.id, destination: c.destination },
                  );
                }}
              >
                <b>
                  {c.destination}
                  {c.prescribed ? " · Current" : ""}
                </b>
                <span>
                  {s.movement
                    ? `${c.occupied} currently stored / ${c.capacity} capacity`
                    : `${c.free_slots} free after incoming work`}
                </span>
                {c.metrics ? (
                  <span>{c.metrics.missed} cargo not protected</span>
                ) : (
                  <span>{c.error}</span>
                )}
                <small>
                  {s.movement ? "Metres" : "Distance"} {c.immediate_distance} +{" "}
                  {c.onward_distance} onward
                </small>
              </button>
            ))}
          </div>
          {selected && (
            <div className="placement-review">
              <h4>{selected.destination} · consequences</h4>
              {selected.movement && (
                <p>
                  Modeled relocation: {clock(selected.movement.start)}–
                  {clock(selected.movement.end)} · empty travel and handovers
                  included.
                </p>
              )}
              {selected.occupancy && (
                <>
                  <h4>Planned stack occupancy</h4>
                  <div className="occupancy-profile">
                    {selected.occupancy.map((p) => (
                      <span key={p.at_minute}>
                        {clock(p.at_minute)}–{clock(p.until_minute)}
                        <br />
                        <b>
                          {p.occupied}/{p.capacity} occupied
                        </b>
                      </span>
                    ))}
                  </div>
                  <small>
                    Conditional on these pickups and placements completing.
                    Actual space is released only by execution.
                  </small>
                </>
              )}
              <ul>
                {selected.impact?.map((i) => (
                  <li key={i.id}>
                    {serviceName(i.id)}: {i.on_time}/{i.total} projected on time
                    ·{" "}
                    {i.delta === null
                      ? "no feasible baseline"
                      : i.delta === 0
                        ? "unchanged"
                        : `${i.delta > 0 ? "+" : ""}${i.delta} vs current`}
                  </li>
                ))}
              </ul>
              <p>
                {selected.prescribed
                  ? "Keeps the existing destination and pickup instructions."
                  : "Updates the relocation destination and later pickup source. Equipment bookings require a new schedule."}
              </p>
              <ul>
                {selected.changes
                  ?.filter(
                    (c) => c.field !== "equipment_id" && c.before !== c.after,
                  )
                  .map((c) => (
                    <li key={`${c.job_id}-${c.field}`}>
                      {cargoName(
                        s.jobs.find((j) => j.id === c.job_id)?.container_id ||
                          "",
                      )}{" "}
                      · {c.field === "target_id" ? "destination" : "pickup"}:{" "}
                      {c.before} → {c.after}
                    </li>
                  ))}
              </ul>
              <button
                className="primary"
                disabled={
                  stale ||
                  blocked ||
                  selected.validation !== "passed" ||
                  selected.prescribed
                }
                onClick={() => setConfirm(true)}
              >
                Review destination change
              </button>
              {confirm && (
                <div
                  className="notice"
                  role="region"
                  aria-label="Confirm placement"
                >
                  <p>
                    Apply {selected.destination} at revision{" "}
                    {result.base_revision}? Container positions remain
                    unchanged.
                  </p>
                  <button
                    disabled={stale || blocked}
                    onClick={() => {
                      command({
                        action: "approve_placement",
                        plan_id: result.id,
                        destination_id: selected.destination,
                      });
                      setConfirm(false);
                      preview(null);
                    }}
                  >
                    Apply destination
                  </button>
                  <button onClick={() => setConfirm(false)}>Cancel</button>
                </div>
              )}
            </div>
          )}
          <details>
            <summary>SQL evidence & assumptions</summary>
            <ul>
              {result.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
            <div className="schedule-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Stack</th>
                    <th>Occupied</th>
                    <th>Incoming</th>
                    <th>Screening</th>
                  </tr>
                </thead>
                <tbody>
                  {result.facts.map((f) => (
                    <tr key={f.destination}>
                      <td>{f.destination}</td>
                      <td>{f.occupied}</td>
                      <td>{f.incoming}</td>
                      <td>
                        {f.excluded_reason || "Eligible for distance shortlist"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  );
}
