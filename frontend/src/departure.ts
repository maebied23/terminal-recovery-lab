import type { State, Job, Cargo } from "./types";

export const cargoName = (id: string) =>
  /^CT-\d+$/.test(id) ? `Container ${Number(id.slice(3))}` : id;
export const serviceName = (id: string) =>
  ({
    "NORTH-RAIL": "North Rail",
    "EAST-RAIL": "East Rail",
    "ROAD-AM": "Morning road service",
    AURORA: "Aurora",
    MERIDIAN: "Meridian",
  })[id] || id;
export const capabilityName = (kind: string) =>
  ({
    yard: "Yard crane",
    quay: "Quay crane",
    tractor: "Terminal tractor",
    gate: "Gate handling",
  })[kind] || kind;
export function equipmentName(s: State, id: string) {
  const equipment = s.equipment.find((e) => e.id === id);
  return equipment
    ? `${capabilityName(equipment.kind)} ${id.split("-").at(-1)}`
    : id;
}
export function placeName(s: State, id: string | null) {
  if (!id) return "In transit";
  const location = s.locations.find((l) => l.id === id);
  if (location?.kind === "yard")
    return `Yard ${location.block} · stack ${id.slice(1)}`;
  const service = s.commitments.find((c) => c.location_id === id);
  return service
    ? serviceName(service.id)
    : { "GATE-IN": "Arrival gate", "TRUCK-OUT": "Road collection" }[id] ||
        location?.label ||
        id;
}
export function readable(s: State, value: string) {
  return value.replace(
    /\b(?:CT-\d+|MV-\d+|YC-\d+|QC-\d+|TT-\d+|GATE-\d+)\b/g,
    (id) => {
      if (id.startsWith("CT-")) return cargoName(id);
      const job = s.jobs.find((j) => j.id === id);
      return job
        ? `${job.kind === "rehandle" ? "relocation" : job.kind} of ${cargoName(job.container_id)}`
        : equipmentName(s, id);
    },
  );
}

// Dependency order includes access work for OTHER cargo. Never sort by move ID.
export function taskChain(s: State, cargoId: string) {
  const jobs = new Map(s.jobs.map((j) => [j.id, j]));
  const seen = new Set<string>(),
    visiting = new Set<string>(),
    ordered: Job[] = [];
  const issues: string[] = [];
  function visit(id: string) {
    if (visiting.has(id)) {
      issues.push(`Dependency cycle at ${id}`);
      return;
    }
    if (seen.has(id)) return;
    const job = jobs.get(id);
    if (!job) {
      issues.push(`Missing predecessor ${id}`);
      return;
    }
    visiting.add(id);
    job.dependencies.forEach(visit);
    visiting.delete(id);
    seen.add(id);
    ordered.push(job);
  }
  s.jobs.filter((j) => j.container_id === cargoId).forEach((j) => visit(j.id));
  return { jobs: ordered, issues };
}
export function cargoReadiness(
  s: State,
  cargo: Cargo,
  destination: string,
  cutoff: number,
) {
  const chain = taskChain(s, cargo.id);
  const finals = chain.jobs.filter(
    (j) =>
      j.container_id === cargo.id &&
      j.target_id === destination &&
      j.kind !== "rehandle",
  );
  const final = finals.at(-1);
  if (final?.status === "completed")
    return {
      label:
        final.completed_at === null
          ? "Needs review"
          : final.completed_at <= cutoff
            ? "Delivered on time"
            : "Delivered late",
      next: null,
      chain,
    };
  const next = chain.jobs.find((j) => j.status !== "completed") || null;
  if (!final || chain.issues.length || !next)
    return { label: "Needs review", next, chain };
  if (s.minute > cutoff) return { label: "Cutoff missed", next, chain };
  if (next.status === "running")
    return {
      label: next.blockers.length ? "Work interrupted" : "Work underway",
      next,
      chain,
    };
  return {
    label: next.blockers.length ? "Waiting / blocked" : "Next move ready",
    next,
    chain,
  };
}

// Only actual start/completion intervals. Running bars end at the observation clock,
// not at an invented future booking. Resource history is retained on completed jobs.
export function equipmentActivity(s: State, equipmentId: string) {
  return s.jobs
    .flatMap((j) =>
      j.stage_history
        ? j.stage_history
            .filter((p) => p.resources.includes(equipmentId))
            .map((p) => ({
              job: j,
              start: p.start,
              end: p.end ?? s.minute,
              active: p.end === null,
            }))
        : j.resources.includes(equipmentId) && j.started_at !== null
          ? [
              {
                job: j,
                start: j.started_at,
                end: j.completed_at ?? s.minute,
                active: j.status === "running",
              },
            ]
          : [],
    )
    .sort((a, b) => a.start - b.start);
}
