import type { State } from "./types";
// Display-only path selection; backend stages remain the timing/feasibility authority.
export function routePoints(s: State, source: string, target: string) {
  if (!s.movement) return [];
  const queue: { id: string; cost: number; path: string[] }[] = [
    { id: source, cost: 0, path: [source] },
  ];
  const seen = new Set<string>();
  while (queue.length) {
    queue.sort((a, b) => a.cost - b.cost || a.id.localeCompare(b.id));
    const n = queue.shift()!;
    if (seen.has(n.id)) continue;
    seen.add(n.id);
    if (n.id === target)
      return n.path
        .map((id) => s.movement!.nodes.find((n) => n.id === id)!)
        .filter(Boolean);
    for (const e of s.movement.edges)
      if (e.source === n.id && !e.closed)
        queue.push({
          id: e.target,
          cost: n.cost + e.metres / e.loaded_mpm,
          path: [...n.path, e.target],
        });
  }
  return [];
}
export function along(points: { x: number; y: number }[], progress: number) {
  const lengths = points
    .slice(1)
    .map((p, i) => Math.hypot(p.x - points[i].x, p.y - points[i].y));
  let left =
    lengths.reduce((a, b) => a + b, 0) * Math.max(0, Math.min(1, progress));
  for (let i = 0; i < lengths.length; i++) {
    if (left <= lengths[i]) {
      const f = lengths[i] ? left / lengths[i] : 0;
      return {
        x: points[i].x + (points[i + 1].x - points[i].x) * f,
        y: points[i].y + (points[i + 1].y - points[i].y) * f,
      };
    }
    left -= lengths[i];
  }
  return points.at(-1) || { x: 0, y: 0 };
}
