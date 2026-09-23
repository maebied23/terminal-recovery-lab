import type { State, Job } from "./types";
export function relatedJobs(s: State, id: string): Job[] {
  const location = s.commitments.find((c) => c.id === id)?.location_id;
  const cargo = s.containers.find((c) => c.visit_id === id);
  const roots = new Set([
    id,
    ...(location ? [location] : []),
    ...(cargo ? [cargo.id] : []),
  ]);
  const direct = new Set(
    s.relationships.edges
      .filter(
        (e) =>
          roots.has(e.target) &&
          [
            "moves",
            "for visit",
            "picks up at",
            "delivers to",
            "assigned to",
            "reserved",
            "used resource",
          ].includes(e.relation),
      )
      .map((e) => e.source),
  );
  for (const j of s.jobs)
    if (
      roots.has(j.id) ||
      s.containers.find((c) => c.id === j.container_id)?.commitment_id === id
    )
      direct.add(j.id);
  return s.jobs
    .filter((j) => direct.has(j.id))
    .sort(
      (a, b) =>
        (({ running: 0, queued: 1, completed: 2 })[a.status as "running"] ??
          3) -
          ({ running: 0, queued: 1, completed: 2 }[b.status as "running"] ??
            3) || a.id.localeCompare(b.id),
    );
}
export function contextIds(s: State, id: string) {
  const jobs = relatedJobs(s, id),
    ids = new Set([id]);
  const seen = new Set<string>();
  for (let i = 0; i < jobs.length; i++) {
    const job = jobs[i];
    if (seen.has(job.id)) continue;
    seen.add(job.id);
    for (const linked of [...job.dependencies, ...job.successors]) {
      const next = s.jobs.find((j) => j.id === linked);
      if (next && !jobs.some((j) => j.id === next.id)) jobs.push(next);
    }
  }
  for (const j of jobs) {
    [
      j.id,
      j.container_id,
      j.source_id,
      j.target_id,
      j.equipment_id,
      ...j.resources,
      ...j.dependencies,
      ...j.successors,
    ].forEach((x) => ids.add(x));
    if (j.commitment_id) ids.add(j.commitment_id);
  }
  return ids;
}
export const actionName = (j: Job) =>
  ({
    rehandle: "Relocate",
    retrieve: "Retrieve",
    discharge: "Unload",
    load: "Load",
    receive: "Receive",
  })[j.kind] || j.kind;
export const jobLabel = (j: Job) =>
  `${j.id} · ${actionName(j)} ${j.container_id}`;

export function journey(s: State, containerId: string): Job[] {
  const ordered: Job[] = [],
    seen = new Set<string>();
  function visit(j: Job) {
    if (seen.has(j.id)) return;
    seen.add(j.id);
    for (const id of j.dependencies) {
      const dep = s.jobs.find((x) => x.id === id);
      if (dep) visit(dep);
    }
    ordered.push(j);
  }
  s.jobs.filter((j) => j.container_id === containerId).forEach(visit);
  return ordered.filter((j) => j.container_id === containerId);
}
