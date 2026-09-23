import { RelationshipLens } from "./RelationPanels";
import { contextIds } from "./relationships";
import type { InputRecord } from "./types";
import { useState } from "react";
import { History, FileText, GitBranch, ArrowRight } from "lucide-react";
import type { State, Event, Source } from "./types";
import { Badge } from "./components";
export function Evidence({
  s,
  events,
  sources,
  selected,
  select,
  replay,
  inputs,
}: {
  inputs: InputRecord[];
  s: State;
  events: Event[];
  sources: Source[];
  selected: string;
  select: (id: string) => void;
  replay: (revision: number | null) => void;
}) {
  const [filter, setFilter] = useState(false);
  const [revision, setRevision] = useState("0");
  const id = selected || s.containers.find((c) => c.commitment_id)?.id || "";
  const ids = contextIds(s, id);
  const shown = events.filter(
    (e) =>
      e.revision <= s.revision &&
      (!filter ||
        ids.has(e.entity_id) ||
        (!!e.payload.job_id && ids.has(e.payload.job_id)) ||
        e.payload.job_ids?.some((j) => ids.has(j))),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">KNOWLEDGE & ACCOUNTABILITY</div>
          <h1>Evidence</h1>
          <p>
            Follow relationships, inspect the source, and distinguish what
            happened from what was known.
          </p>
        </div>
      </div>
      <div className="evidence-grid">
        <section className="panel">
          <div className="section-heading">
            <h3>
              <GitBranch size={17} /> Relationship lens
            </h3>
            <span>Selected: {id}</span>
          </div>
          <RelationshipLens s={s} id={id} select={select} />
          <p className="micro">
            A projection of relational keys, not a separate graph database.
            Select a connected entity to continue the trace.
          </p>
        </section>
        <section className="panel">
          <div className="section-heading">
            <h3>
              <History size={17} /> Known at revision
            </h3>
          </div>
          <p>
            Open the immutable snapshot the planner could see. Later corrections
            remain separate.
          </p>
          <div className="input-row">
            <input
              aria-label="Historical revision"
              type="number"
              min="0"
              max={s.revision}
              value={revision}
              onChange={(e) => setRevision(e.target.value)}
            />
            <button
              className="primary"
              onClick={() => replay(Number(revision))}
            >
              Inspect snapshot
            </button>
          </div>
          <button className="text-button" onClick={() => replay(null)}>
            Return to current state <ArrowRight size={14} />
          </button>
          <h4>Availability observations</h4>
          {s.observations.length ? (
            s.observations
              .slice(-4)
              .reverse()
              .map((o, i) => (
                <div className="observation" key={i}>
                  <b>
                    {o.entity_id} · {o.value}
                  </b>
                  <span>
                    Occurred minute {o.valid_minute} / recorded minute{" "}
                    {o.recorded_minute}
                  </span>
                  <small>
                    Revision {o.revision}
                    {o.supersedes
                      ? ` · supersedes belief at r${o.supersedes}`
                      : ""}
                  </small>
                </div>
              ))
          ) : (
            <p className="muted">
              No availability observation yet. Scenario Lab can inject a failure
              or late correction.
            </p>
          )}
        </section>
      </div>
      <section className="panel">
        <div className="section-heading">
          <h3>Event ledger · recent events at this revision</h3>
          <label>
            <input
              type="checkbox"
              checked={filter}
              onChange={(e) => setFilter(e.target.checked)}
            />{" "}
            Selected object and connected work
          </label>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Revision</th>
                <th>Occurrence</th>
                <th>Recorded at</th>
                <th>Entity</th>
                <th>Event</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((e) => (
                <tr key={e.id}>
                  <td>
                    <button
                      className="text-button"
                      onClick={() => replay(e.revision)}
                    >
                      r{e.revision}
                    </button>
                  </td>
                  <td>minute {e.valid_minute}</td>
                  <td className="mono">
                    {new Date(e.recorded_at).toLocaleTimeString()}
                  </td>
                  <td>
                    <button
                      className="text-button"
                      onClick={() => select(e.entity_id)}
                    >
                      {e.entity_id}
                    </button>
                  </td>
                  <td>
                    {e.payload.message}
                    <small>
                      {e.kind} ·{" "}
                      {e.command_id
                        ? `command ${e.command_id.slice(0, 8)}`
                        : "simulation clock"}
                    </small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!shown.length && (
            <div className="empty">
              Events appear when the simulation or an approved action changes
              state.
            </div>
          )}
        </div>
      </section>
      <section className="panel">
        <h3>Input provenance rehearsal · separate from operational state</h3>
        <p>
          Accepted means the envelope and identity passed checks. It does not
          confirm equipment state or move cargo. This ledger is ingestion-time
          history, independent of the operational snapshot above.
        </p>
        {inputs.map((r) => (
          <div className="readiness-item" key={r.id}>
            <b>
              {r.source} / {r.source_event_id} · {r.status}
            </b>
            <span>
              {r.payload.entity_id} → {r.payload.value} · occurred minute{" "}
              {r.event_time}
            </span>
            <small>
              Received {new Date(r.recorded_at).toLocaleString()} ·{" "}
              {r.reason ||
                "Validated and retained; not applied to operational state"}
            </small>
          </div>
        ))}
        {!inputs.length && (
          <p>
            No input envelopes recorded. Use Scenario Lab to rehearse a feed.
          </p>
        )}
      </section>
      <div className="section-heading">
        <h3>
          <FileText size={17} /> Sources, assumptions & executable rules
        </h3>
        <span>Reference documents never silently become policy</span>
      </div>
      <div className="source-grid">
        {sources.map((source) => (
          <article className="panel source" key={source.id}>
            <div>
              <span className="eyebrow">{source.id}</span>
              <Badge value={source.review_status} />
            </div>
            <h3>{source.title}</h3>
            <p>{source.body}</p>
            <footer>
              {source.executable
                ? "Enforced by domain rules"
                : "Context / assumption only"}
              <small>
                {source.source.startsWith("http") ? (
                  <a href={source.source} target="_blank" rel="noreferrer">
                    Open reference ↗
                  </a>
                ) : (
                  source.source
                )}
              </small>
            </footer>
          </article>
        ))}
      </div>
    </>
  );
}
