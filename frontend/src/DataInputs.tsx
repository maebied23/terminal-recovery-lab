import { useEffect, useState, useRef } from "react";
import type { State } from "./types";
import { clock } from "./types";
import { cargoName, equipmentName, serviceName, placeName } from "./departure";
import "./data-inputs.css";

type Pack = {
  id: string;
  title: string;
  description?: string;
  valid: boolean;
  digest?: string;
  counts?: Record<string, number>;
  events?: number;
  error?: string;
  changes?: unknown[];
};
type Receipt = {
  id: number;
  ordinal: number;
  envelope: {
    source: string;
    event_id: string;
    external_id: string;
    kind: string;
    value: unknown;
  };
  status: string;
  reason: string;
  entity_id: string | null;
  field: string | null;
  observed_minute: number | null;
  receive_minute: number;
  applied_revision: number;
  before_value: unknown;
  after_value: unknown;
  delivery_lag_minutes: number | null;
};
type Report = {
  context?: string;
  revision: number;
  minute?: number;
  dataset: null | {
    pack_id: string;
    digest: string;
    manifest: {
      title: string;
      description: string;
      assumptions: string[];
      shift_start: string;
      units: Record<string, string>;
    };
    validation: { counts: Record<string, number>; changes: unknown[] };
  };
  counts?: Record<string, number>;
  receipts?: Receipt[];
  impact?:
    | null
    | {
        commitment_id: string;
        cargo_visits: number;
        moves: number;
        cutoff: number;
        work: { job_id: string; container_id: string; visit_id: string }[];
      }[];
  impact_note?: string;
  source_rows?: { file_name: string; row_number: number; raw: unknown }[];
  windows?: {
    equipment_id: string;
    start_minute: number;
    end_minute: number;
    permits_dispatch: boolean;
    source: string;
  }[];
  origin?: unknown;
};

export function DataInputs({
  s,
  run,
  selected,
  request,
  role,
  activate,
  inspect,
  historical,
  allowImport,
}: {
  s: State;
  run: string;
  selected: string;
  request: (url: string, body?: unknown) => Promise<any>;
  role: string;
  activate: (run: string) => void;
  inspect: (entity: string) => void;
  historical: boolean;
  allowImport: boolean;
}) {
  const [packs, setPacks] = useState<Pack[]>([]),
    [packId, setPackId] = useState(s.dataset?.pack_id || "baseline-shift"),
    [loadedReport, setReport] = useState<Report | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [entity, setEntity] = useState("YC-1");
  const [feed, setFeed] = useState<{ run: string; received: number; applied: number; duplicates: number; stale: number; quarantined: number; last_received_at: string | null } | null>(null);
  useEffect(() => {
    let active = true;
    setFeed(null);
    if (historical) return;
    const refresh = () => request(`/api/integrations/equipment/status?run=${encodeURIComponent(run)}`)
      .then(r => { if (active) setFeed({ ...r, run }); }).catch(() => { if (active) setFeed(null); });
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => { active = false; clearInterval(timer); };
  }, [request, run, s.revision, historical]);
  const target = selected || entity;
  const currentEquipment = s.equipment.find((e) => e.id === target);
  const currentCargo = s.containers.find((c) => c.id === target);
  const observationName = (kind: string) =>
    ({
      "equipment.status": "Equipment availability",
      "container.position": "Observed cargo position",
      "container.release": "Authority release",
    })[kind] || kind;
  const observationValue = (r: Receipt) => {
    const value = r.envelope.value;
    if (r.envelope.kind === "container.release" && typeof value === "boolean")
      return value ? "Released" : "On hold";
    if (r.envelope.kind === "equipment.status" && typeof value === "string")
      return value === "failed"
        ? "Unavailable"
        : value === "available"
          ? "Available"
          : value;
    if (
      r.envelope.kind === "container.position" &&
      typeof value === "object" &&
      value !== null &&
      "location_id" in value &&
      "tier" in value &&
      typeof value.location_id === "string" &&
      typeof value.tier === "number"
    )
      return `${placeName(s, value.location_id)} · level ${value.tier + 1}`;
    return JSON.stringify(value);
  };
  const context = `${run}/${s.revision}/${target}`;
  const report = loadedReport?.context === context ? loadedReport : null;
  const importAttempt = useRef<{ digest: string; id: string } | null>(null);
  useEffect(() => {
    let active = true;
    request("/api/datasets")
      .then((rows) => {
        if (active) setPacks(rows);
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
    };
  }, [request]);
  useEffect(() => {
    let active = true;
    setReport(null);
    request(
      `/api/datasets/evidence?run=${encodeURIComponent(run)}&revision=${s.revision}&entity=${encodeURIComponent(target)}`,
    )
      .then((r) => {
        if (active) {
          setReport({ ...r, context: `${run}/${s.revision}/${target}` });
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
    };
  }, [request, run, s.revision, target]);
  const pack = packs.find((p) => p.id === packId);
  async function importData() {
    if (!pack?.valid || !pack.digest) return;
    setBusy(true);
    setError("");
    try {
      if (importAttempt.current?.digest !== pack.digest)
        importAttempt.current = {
          digest: pack.digest,
          id: crypto.randomUUID(),
        };
      const result = await request("/api/datasets/import", {
        pack_id: pack.id,
        expected_digest: pack.digest,
        request_id: importAttempt.current!.id,
      });
      importAttempt.current = null;
      activate(result.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const label = (id: string) =>
    s.equipment.some((e) => e.id === id)
      ? equipmentName(s, id)
      : s.containers.some((c) => c.id === id)
        ? cargoName(id)
        : id;
  return (
    <section
      className="data-inputs panel"
      aria-label="Input datasets and evidence"
    >
      <div className="section-heading">
        <div>
          <div className="eyebrow">INPUTS → STATE → CONNECTED WORK</div>
          <h2>
            {allowImport
              ? "Start with inspectable data"
              : "Where this state came from"}
          </h2>
        </div>
        <span className="outlined-label">SYNTHETIC INPUTS</span>
      </div>
      <p>
        Load a known starting world, then follow observations into cargo,
        equipment and departure decisions.
      </p>
      {!historical && feed?.run === run && <details className="panel" aria-label="Equipment observation feed">
        <summary>Equipment feed · {feed.received ? `${feed.applied} applied · ${feed.quarantined} quarantined` : "No external receipts"}</summary>
        <p>Synthetic sender · {feed.last_received_at ? `Last received ${new Date(feed.last_received_at).toLocaleString()}` : "Not yet connected"}</p>
        <p>{feed.duplicates} duplicate · {feed.stale} stale. Sender silence does not change equipment availability.</p>
        <p>Select equipment below to inspect accepted inputs and affected work.</p>
      </details>}
      {error && (
        <p role="alert" className="data-error">
          {error}
        </p>
      )}
      {allowImport && (
        <div className="data-import-grid">
          <div>
            <label htmlFor="input-pack">Input pack</label>
            <select
              id="input-pack"
              value={packId}
              onChange={(e) => setPackId(e.target.value)}
            >
              {packs.map((p) => (
                <option value={p.id} key={p.id}>
                  {p.title}
                  {p.valid ? "" : " · invalid"}
                </option>
              ))}
            </select>
            <p>{pack?.description || pack?.error}</p>
            {pack?.counts && (
              <p className="data-note">
                {pack.counts.containers} containers · {pack.counts.work_orders}{" "}
                work orders · {pack.events} test observations
              </p>
            )}
            <button
              className="primary"
              disabled={
                !pack?.valid || role !== "scenario-admin" || busy || historical
              }
              onClick={importData}
            >
              {busy
                ? "Validating and importing…"
                : "Import as a new paused shift"}
            </button>
            {role !== "scenario-admin" && (
              <p className="data-note">
                Unlock the scenario administrator controls below to import.
                Existing shifts are preserved.
              </p>
            )}
          </div>
          <div>
            <h3>What importing means</h3>
            <ol>
              <li>Verify file versions and checksums.</li>
              <li>Validate identities, visits, positions and dependencies.</li>
              <li>Save the whole starting state or reject the import.</li>
              <li>Deliver test observations as you step the simulation.</li>
            </ol>
            <p className="data-note">
              No job starts during import. Test events are outside planner
              snapshots until delivered. This is a replay adapter, not a live
              terminal connector.
            </p>
            <details>
              <summary>Variation from the shared baseline</summary>
              <pre>{JSON.stringify(pack?.changes || [], null, 2)}</pre>
              <p className="data-note">
                Outage and imperfect-information packs also have an event
                stream. Baseline already contains the known Container 121 access
                problem.
              </p>
            </details>
          </div>
        </div>
      )}
      {!report && !error && (
        <p role="status">Loading input evidence for revision {s.revision}…</p>
      )}
      {report && !report.dataset && (
        <p className="data-note">
          {report.origin
            ? "This is a fork of an imported shift. It retains the inherited state and provenance, but does not replay the parent’s future input stream. Inspect the parent for its source ledger."
            : "This shift was created by the original seed generator. Import a pack in Scenario lab to inspect source rows and delivered observations."}
        </p>
      )}
      {report?.dataset && (
        <>
          <div className="data-current">
            <b>{report.dataset.manifest.title}</b>
            <span>
              {historical ? "Historical evidence" : "Current input evidence"} ·{" "}
              {clock(s.minute)} · revision {report.revision}
            </span>
            <p>{report.dataset.manifest.description}</p>
            <small>
              Dataset origin: {report.dataset.manifest.shift_start} · All
              durations in minutes, weights in tonnes.
            </small>
          </div>
          <div className="data-counts">
            {Object.entries(report.counts || {}).map(([key, value]) => (
              <div key={key}>
                <strong>{value}</strong>
                <span>
                  {{
                    awaiting_delivery: "Not delivered yet",
                    applied: "Applied to state",
                    duplicates: "Duplicate receipts",
                    stale: "Older observations",
                    quarantined: "Needs correction",
                  }[key] || key}
                </span>
              </div>
            ))}
          </div>
          <p className="data-note">
            An applied input changes operational state. A duplicate, older
            observation or quarantined record does not. Delivery time and
            observation time are shown separately.
          </p>
          <h3>Follow an input’s connections</h3>
          <div className="data-entity">
            <select
              aria-label="Trace input entity"
              value={target}
              onChange={(e) => {
                setEntity(e.target.value);
                inspect(e.target.value);
              }}
            >
              {![
                ...s.equipment,
                ...s.containers.filter((c) => c.commitment_id),
              ].some((e) => e.id === target) && (
                <option value={target}>{target}</option>
              )}
              {s.equipment.map((e) => (
                <option key={e.id} value={e.id}>
                  {equipmentName(s, e.id)}
                </option>
              ))}
              {s.containers
                .filter((c) => c.commitment_id)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {cargoName(c.id)}
                  </option>
                ))}
            </select>
            <button className="text-button" onClick={() => inspect(target)}>
              Inspect {label(target)}
            </button>
          </div>
          <p className="data-note">{report.impact_note}</p>
          {currentEquipment && (
            <p>
              <b>Accepted state:</b>{" "}
              {currentEquipment.status === "failed"
                ? "Unavailable"
                : currentEquipment.job_id
                  ? "In use"
                  : "Available"}
              {currentEquipment.within_shift === false
                ? " · outside published shift"
                : ""}{" "}
              at {clock(s.minute)}.
            </p>
          )}
          {currentCargo && (
            <p>
              <b>Accepted state:</b> {placeName(s, currentCargo.location_id)}
              {currentCargo.location_id
                ? ` · level ${currentCargo.tier + 1}`
                : ""}{" "}
              · {currentCargo.released ? "Released" : "On hold"} at{" "}
              {clock(s.minute)}.
            </p>
          )}
          {report.impact && (
            <div className="data-impact">
              {report.impact.length ? (
                report.impact.map((row) => (
                  <div key={row.commitment_id}>
                    <b>
                      {serviceName(row.commitment_id)} · {clock(row.cutoff)}
                    </b>
                    <p>
                      {row.cargo_visits} distinct cargo visits · {row.moves}{" "}
                      connected active moves
                    </p>
                    <div>
                      {row.work.map((w) => (
                        <button
                          key={w.job_id}
                          onClick={() => inspect(w.job_id)}
                        >
                          {cargoName(w.container_id)} <small>{w.job_id}</small>
                        </button>
                      ))}
                    </div>
                  </div>
                ))
              ) : (
                <p>
                  No active assigned or dependent work connects this entity to a
                  departure.
                </p>
              )}
            </div>
          )}
          {!!report.windows?.length && (
            <p>
              Published availability:{" "}
              {report.windows
                .map(
                  (w) =>
                    `${w.source} · ${clock(w.start_minute)}–${clock(w.end_minute)} (end exclusive), ${w.permits_dispatch ? "within shift" : "outside shift"} at this snapshot`,
                )
                .join("; ")}
              . Availability permits dispatch; it is not a reservation.
            </p>
          )}
          <details>
            <summary>
              Original source rows for {label(target)} ·{" "}
              {report.source_rows?.length || 0}
            </summary>
            <p className="data-note">
              Immutable baseline input rows. The variation below is applied on
              top; these are not the current positions after simulation or
              observations.
            </p>
            {report.source_rows?.map((r) => (
              <div key={r.file_name + r.row_number}>
                <b>
                  {r.file_name} · row {r.row_number}
                </b>
                <pre>{JSON.stringify(r.raw, null, 2)}</pre>
              </div>
            ))}
            <b>Imported variation</b>
            <pre>
              {JSON.stringify(report.dataset.validation.changes, null, 2)}
            </pre>
          </details>
          <h3 className="data-ledger-title">Delivered observations</h3>
          {report.receipts?.length ? (
            <div className="data-receipts">
              {report.receipts.map((r) => (
                <article key={r.id}>
                  <div className="section-heading">
                    <b>
                      {r.entity_id
                        ? label(r.entity_id)
                        : r.envelope.external_id}
                    </b>
                    <span className={`receipt-status ${r.status}`}>
                      {r.status}
                    </span>
                  </div>
                  <p>
                    {observationName(r.envelope.kind)} ·{" "}
                    <b>{observationValue(r)}</b>
                  </p>
                  <p className="data-note">
                    Observed{" "}
                    {r.observed_minute === null
                      ? "unresolved"
                      : clock(r.observed_minute)}{" "}
                    → delivered {clock(r.receive_minute)} · known at revision{" "}
                    {r.applied_revision}
                  </p>
                  <p>{r.reason}</p>
                  <details>
                    <summary>Source and recorded effect</summary>
                    <p>
                      {r.envelope.kind} · {r.envelope.external_id}
                    </p>
                    <p>
                      {r.envelope.source} / {r.envelope.event_id}
                    </p>
                    <pre>
                      {JSON.stringify(
                        {
                          before: r.before_value,
                          after: r.after_value,
                          receipt_id: r.id,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </article>
              ))}
            </div>
          ) : (
            <p>
              No test observations had been delivered at this revision. Advance
              the paused shift to receive them.
            </p>
          )}
          <details>
            <summary>Dataset assumptions and fingerprint</summary>
            <ul>
              {report.dataset.manifest.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
            <code>{report.dataset.digest}</code>
          </details>
        </>
      )}
    </section>
  );
}
