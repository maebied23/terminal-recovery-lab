export type TimedWork = {
  job_id: string;
  start: number;
  end: number;
  resources: string[];
  source_id: string;
  target_id: string;
};
export function bookingChanges(base: TimedWork[], rows: TimedWork[]) {
  const old = new Map(base.map((r) => [r.job_id, r]));
  return rows.map((r) => {
    const b = old.get(r.job_id);
    return {
      job_id: r.job_id,
      changes: !b
        ? ["Added work"]
        : [
            ...(b.start !== r.start || b.end !== r.end ? ["Timing"] : []),
            ...(b.resources.join("|") !== r.resources.join("|")
              ? ["Equipment"]
              : []),
            ...(b.source_id !== r.source_id || b.target_id !== r.target_id
              ? ["Route"]
              : []),
          ],
    };
  });
}

export function reservationLabel(
  mode: "proposal" | "approved",
  planStatus: string | undefined,
  jobStatus: string | undefined,
  frozen: boolean,
) {
  if (mode === "proposal") return frozen ? "Frozen at comparison" : "Proposed";
  if (jobStatus === "completed") return "Completed";
  if (jobStatus === "running") return "Occupied";
  return ["interrupted", "withdrawn", "completed"].includes(planStatus || "")
    ? "Released"
    : "Booked";
}
