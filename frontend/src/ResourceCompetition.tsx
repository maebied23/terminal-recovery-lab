import type { State } from "./types";
import type { Diagnosis } from "./Diagnosis";
import { equipmentName, serviceName } from "./departure";
import { clock } from "./types";
export function ResourceCompetition({
  s,
  diagnosis,
  select,
}: {
  s: State;
  diagnosis: Diagnosis | null;
  select: (id: string) => void;
}) {
  return (
    <details className="panel resource-competition" open>
      <summary>Shared equipment demand</summary>
      <div className="competition-grid">
        {s.equipment.map((e) => {
          const jobs = s.jobs.filter(
            (j) =>
              j.status !== "completed" &&
              j.requirements.some((r) => r.eligible.includes(e.id)),
          );
          const services = Array.from(
            new Set(jobs.map((j) => j.commitment_id).filter(Boolean)),
          ) as string[];
          const calendar = diagnosis?.calendar.find(
            (c) => c.equipment_id === e.id,
          );
          return (
            <button key={e.id} onClick={() => select(e.id)}>
              <b>{equipmentName(s, e.id)}</b>
              <span>
                {e.status === "failed"
                  ? "Failed"
                  : e.job_id
                    ? "Occupied"
                    : "Available now"}{" "}
                · {jobs.length} compatible jobs
              </span>
              <small>
                {services.map(serviceName).join(" · ") || "No outbound demand"}
              </small>
              <small>
                {calendar?.windows
                  .map((w) => `${clock(w.start)}–${clock(w.end)}`)
                  .join(", ") || "No published calendar"}
              </small>
            </button>
          );
        })}
      </div>
    </details>
  );
}
