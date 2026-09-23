import type { State, Job } from "./types";
import { clock } from "./types";
import { equipmentName, cargoName, placeName } from "./departure";

export function MovementDetail({ s, job }: { s: State; job: Job }) {
  if (!s.movement) return null;
  const cargo = s.containers.find((c) => c.id === job.container_id);
  const planned = s.schedule?.rows.find((r) => r.job_id === job.id);
  const stages =
    job.movement_stages || planned?.stages || job.movement_preview?.stages;
  const current = job.movement_stages?.[job.stage_index || 0];
  const owner = cargo?.custody;
  const failed = [
    ...new Set(
      (stages || [])
        .slice(job.stage_index || 0)
        .flatMap((p) => p.resources || []),
    ),
  ].filter((id) => s.equipment.find((e) => e.id === id)?.status === "failed");
  const interrupted = ["interrupted", "withdrawn"].includes(
    s.schedule?.status || "",
  );
  return (
    <section
      className="movement-detail panel"
      aria-label="Movement and custody"
    >
      <div className="section-heading">
        <h3>{cargoName(job.container_id)} · Movement</h3>
        <span>
          {job.status === "running"
            ? current?.name
            : job.status === "completed"
              ? "Placed"
              : planned
                ? "Booked"
                : "Not booked"}
        </span>
      </div>
      <div className="movement-facts">
        <div>
          <small>Current location / holder</small>
          <strong>
            {owner?.kind === "equipment"
              ? equipmentName(s, owner.id)
              : placeName(s, owner?.id || cargo?.location_id || "")}
          </strong>
        </div>
        <div>
          <small>Instructed destination</small>
          <strong>{placeName(s, job.target_id)}</strong>
        </div>
        <div>
          <small>Next action</small>
          <strong>
            {job.waiting_reason || failed.length || interrupted
              ? "Review recovery before continuing"
              : job.status === "running"
                ? "Track execution"
                : planned
                  ? "Step or run booked work"
                  : "Compare and book equipment"}
          </strong>
        </div>
      </div>
      {interrupted && (
        <p className="notice warning">
          Schedule interrupted.{" "}
          {failed.length
            ? `${failed.map((e) => equipmentName(s, e)).join(", ")} unavailable. `
            : ""}
          Current cargo ownership is retained; future bookings are released.
          Repair the issue and review recovery.
        </p>
      )}
      {job.waiting_reason && (
        <p className="notice warning">{job.waiting_reason}</p>
      )}
      {job.movement_error && (
        <p className="notice warning">{job.movement_error}</p>
      )}
      {stages && (
        <small>
          {job.status === "running"
            ? "Original stage timing · current holder above reflects actual execution"
            : "Movement stages"}
        </small>
      )}
      {stages && (
        <ol className="movement-stages">
          {stages.map((p, i) => (
            <li
              key={i}
              className={
                job.status === "running" && i === job.stage_index
                  ? "current"
                  : ""
              }
            >
              <b>
                {i + 1}. {p.name}
              </b>
              <span>
                {clock(p.start)}–{clock(p.end)}
              </span>
              <span>
                {p.resources?.map((e) => equipmentName(s, e)).join(" + ")}
              </span>
              {p.route && (
                <small>
                  {p.route.metres} m · {p.route.loaded ? "Loaded" : "Empty"}{" "}
                  travel · {p.route.minutes} min
                </small>
              )}
            </li>
          ))}
        </ol>
      )}
      <small>
        {job.status === "queued" && !planned
          ? "Estimate from last confirmed equipment positions; compare a schedule for feasible bookings. "
          : ""}
        Synthetic rates · current state and proposed work are separate.
      </small>
    </section>
  );
}
