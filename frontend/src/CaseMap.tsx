import { routePoints, along } from "./movement";
import { useId, useState } from "react";
import type { State, Job } from "./types";
import { cargoName, serviceName } from "./departure";

const routeColors = ["#eac16a", "#70d4d0", "#aba6ff", "#f399ac"];
export function CaseMap({
  s,
  jobs,
  selected,
  select,
  preview,
  mode = "instructions",
}: {
  mode?: "instructions" | "proposal" | "approved";
  s: State;
  jobs: Job[];
  selected: string;
  select: (id: string) => void;
  preview?: { job_id: string; destination: string } | null;
}) {
  const uid = useId().replace(/:/g, "");
  const [background, setBackground] = useState(false);
  const [zoom, setZoom] = useState(1);
  const relocation = jobs.find((j) => j.id === preview?.job_id);
  const routes = jobs.map((j) => {
    if (!preview || !relocation) return j;
    if (j.id === preview.job_id)
      return { ...j, target_id: preview.destination };
    if (
      j.container_id === relocation.container_id &&
      j.dependencies.includes(relocation.id) &&
      j.source_id === relocation.target_id
    )
      return { ...j, source_id: preview.destination };
    return j;
  });
  const involved = new Set(routes.flatMap((j) => [j.source_id, j.target_id]));
  const relevant = [
    ...s.locations.filter((l) => involved.has(l.id)),
    ...routes.flatMap((j) => routePoints(s, j.source_id, j.target_id)),
  ];
  const bounds =
    !background && relevant.length
      ? {
          x: Math.max(0, Math.min(...relevant.map((l) => l.x)) - 110),
          y: Math.max(0, Math.min(...relevant.map((l) => l.y)) - 90),
          right: Math.min(1100, Math.max(...relevant.map((l) => l.x)) + 145),
          bottom: Math.min(690, Math.max(...relevant.map((l) => l.y)) + 85),
        }
      : { x: 0, y: 0, right: 1100, bottom: 690 };
  const width = Math.max(380, bounds.right - bounds.x),
    height = Math.max(250, bounds.bottom - bounds.y);
  const viewBox = `${bounds.x + (width * (1 - 1 / zoom)) / 2} ${bounds.y + (height * (1 - 1 / zoom)) / 2} ${width / zoom} ${height / zoom}`;
  const pick = (id: string) => ({
    role: "button" as const,
    tabIndex: 0,
    onClick: () => select(id),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        select(id);
      }
    },
  });
  return (
    <section className="case-map" aria-label="Selected work map">
      <header>
        <div>
          <h2>Terminal map</h2>
          <span>
            Schematic · observed inventory /{" "}
            {mode === "proposal"
              ? "proposed bookings"
              : mode === "approved"
                ? "bookings / instructions"
                : "instructed routes"}
          </span>
        </div>
        <div className="map-tools">
          <button
            onClick={() => setBackground(!background)}
            aria-pressed={background}
          >
            All work
          </button>
          <button
            aria-label="Zoom map"
            onClick={() => setZoom(zoom === 1 ? 1.25 : 1)}
          >
            {zoom === 1 ? "Zoom +" : "Reset"}
          </button>
        </div>
      </header>
      <div className="map-observations">
        {Array.from(new Set(jobs.map((j) => j.container_id))).map((id) => {
          const c = s.containers.find((c) => c.id === id);
          return (
            <span key={id}>
              {cargoName(id)}: {c?.location_id || "in transit"}
            </span>
          );
        })}
      </div>
      <div className="case-map-scroll">
        <svg
          viewBox={viewBox}
          role="group"
          aria-label="Labeled terminal stacks and ordered cargo movements"
        >
          <defs>
            {routeColors.map((color, i) => (
              <marker
                key={i}
                id={`${uid}arrow${i}`}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M0 0L10 5L0 10Z" fill={color} />
              </marker>
            ))}
            <pattern
              id={`${uid}water`}
              width="36"
              height="28"
              patternUnits="userSpaceOnUse"
            >
              <path d="M0 14h15" stroke="#345562" strokeWidth="1" />
            </pattern>
          </defs>
          <rect width="1100" height="690" fill="#192f39" />
          <rect width="1100" height="166" fill={`url(#${uid}water)`} />
          <text x="38" y="38" className="map-zone">
            NORTH CHANNEL
          </text>
          <rect
            x="35"
            y="173"
            width="1030"
            height="494"
            rx="18"
            fill="#243c45"
          />
          <path d="M40 171H1060" stroke="#92a7a6" strokeWidth="5" />
          <path
            d="M70 210H1015M70 375H1015M70 520H1015M90 210V638M1015 210V638"
            stroke="#142c35"
            strokeWidth="22"
            fill="none"
          />
          <path
            d="M70 210H1015M70 375H1015M70 520H1015"
            stroke="#627b80"
            strokeDasharray="10 12"
            fill="none"
          />
          {["A", "B", "C", "D", "E", "F"].map((block) => {
            const ls = s.locations.filter(
              (l) => l.kind === "yard" && l.block === block,
            );
            if (!ls.length) return null;
            const x = Math.min(...ls.map((l) => l.x)) - 35,
              y = ls[0].y - 50;
            return (
              <g key={block}>
                <rect
                  x={x}
                  y={y}
                  width="192"
                  height="130"
                  rx="10"
                  fill="#304951"
                  stroke="#4b656b"
                />
                <text x={x + 12} y={y + 10} className="map-zone">
                  YARD {block}
                </text>
              </g>
            );
          })}
          {s.locations
            .filter((l) => l.kind !== "yard")
            .map((l) => {
              const service = s.commitments.find((c) => c.location_id === l.id);
              return (
                <g
                  key={l.id}
                  {...pick(l.id)}
                  aria-label={`${service ? serviceName(service.id) : l.label}`}
                >
                  <rect
                    x={l.x - 86}
                    y={l.y - 19}
                    width="172"
                    height="40"
                    rx={l.kind === "vessel" ? 19 : 5}
                    fill={involved.has(l.id) ? "#365e64" : "#2b4550"}
                    stroke={involved.has(l.id) ? "#70d4d0" : "#69818a"}
                  />
                  <text
                    x={l.x}
                    y={l.y + 6}
                    textAnchor="middle"
                    className="map-location-label"
                  >
                    {service
                      ? serviceName(service.id)
                      : l.kind === "gate"
                        ? "Arrival gate"
                        : "Road collection"}
                  </text>
                </g>
              );
            })}
          {background &&
            s.jobs
              .filter(
                (j) =>
                  !jobs.some((x) => x.id === j.id) && j.status !== "completed",
              )
              .map((j) => {
                const a = s.locations.find((l) => l.id === j.source_id),
                  b = s.locations.find((l) => l.id === j.target_id);
                if (!a || !b) return null;
                return (
                  <path
                    key={j.id}
                    d={`M${a.x} ${a.y}L${b.x} ${b.y}`}
                    stroke="#788d92"
                    opacity=".15"
                    strokeWidth="2"
                  />
                );
              })}
          {s.locations
            .filter((l) => l.kind === "yard")
            .map((l) => {
              const n = s.containers.filter(
                (c) => c.location_id === l.id,
              ).length;
              const incoming = s.jobs.filter(
                (j) => j.target_id === l.id && j.status === "running",
              ).length;
              return (
                <g
                  key={l.id}
                  {...pick(l.id)}
                  aria-label={`Stack ${l.id}, ${n} occupied, ${l.capacity - n - incoming} free`}
                >
                  <rect
                    x={l.x - 15}
                    y={l.y - 10}
                    width="30"
                    height="48"
                    rx="3"
                    fill={involved.has(l.id) ? "#52716e" : "#3f5960"}
                    stroke={involved.has(l.id) ? "#d5e9d8" : "#698087"}
                    strokeWidth={involved.has(l.id) ? 2 : 1}
                  />
                  {Array.from({ length: Math.min(n, l.capacity) }, (_, i) => (
                    <rect
                      key={i}
                      x={l.x - 11}
                      y={l.y + 32 - i * 5}
                      width="22"
                      height="3"
                      fill={involved.has(l.id) ? "#c0d0aa" : "#8ca0a3"}
                    />
                  ))}
                  <text
                    x={l.x}
                    y={l.y - 19}
                    textAnchor="middle"
                    className="map-location-label"
                  >
                    {l.id}
                  </text>
                  <text
                    x={l.x}
                    y={l.y + 55}
                    textAnchor="middle"
                    className="map-capacity"
                  >
                    {n}/{l.capacity}
                  </text>
                </g>
              );
            })}
          {s.movement?.edges
            .filter(
              (e) =>
                background ||
                involved.has(e.source) ||
                involved.has(e.target) ||
                (e.source.startsWith("J") && e.target.startsWith("J")),
            )
            .slice()
            .sort((a, b) => Number(a.closed) - Number(b.closed))
            .map((e) => {
              const a = s.movement!.nodes.find((n) => n.id === e.source),
                b = s.movement!.nodes.find((n) => n.id === e.target);
              return a && b ? (
                <line
                  key={e.id}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={e.closed ? "#ef8585" : "#69848b"}
                  strokeWidth={e.closed ? 4 : 2}
                  opacity={0.5}
                  strokeDasharray={e.closed ? "5 5" : undefined}
                >
                  <title>
                    {e.id} · {e.metres} m{e.closed ? " · Closed" : ""}
                  </title>
                </line>
              ) : null;
            })}
          {routes
            .filter((j) => j.status === "running")
            .map((j) => {
              const stage = j.movement_stages?.[j.stage_index || 0];
              if (stage?.kind !== "empty" || !stage.route || !s.movement)
                return null;
              const pathNodes = [
                stage.route.source,
                ...stage.route.edges.map(
                  (id) => s.movement!.edges.find((e) => e.id === id)!.target,
                ),
              ];
              const points = pathNodes
                .map((id) => s.movement!.nodes.find((n) => n.id === id)!)
                .filter(Boolean);
              const p = along(
                points,
                1 - (j.stage_remaining || 0) / (stage.end - stage.start),
              );
              return (
                <g key={`empty-${j.id}`}>
                  <path
                    d={points
                      .map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`)
                      .join(" ")}
                    stroke="#d59eea"
                    strokeWidth={3}
                    strokeDasharray="4 6"
                    fill="none"
                  />
                  <rect
                    x={p.x - 8}
                    y={p.y - 6}
                    width={16}
                    height={12}
                    fill="#d59eea"
                  />
                  <text x={p.x + 12} y={p.y - 8} fill="#eac9f6" fontSize={12}>
                    Empty tractor
                  </text>
                  <title>
                    Empty tractor repositioning; container remains at its source
                  </title>
                </g>
              );
            })}
          {routes.map((j, i) => {
            const a = s.locations.find((l) => l.id === j.source_id),
              b = s.locations.find((l) => l.id === j.target_id);
            if (!a || !b) return null;
            const color = routeColors[i % routeColors.length],
              lane = 370 + i * 18;
            const points = routePoints(s, j.source_id, j.target_id);
            const path = s.movement
              ? points.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ")
              : `M${a.x} ${a.y + 8}V${lane}H${b.x}V${b.y}`;
            const current = j.movement_stages?.[j.stage_index || 0];
            const marker = s.movement
              ? current?.kind === "transfer"
                ? along(
                    points,
                    1 -
                      (j.stage_remaining || 0) / (current.end - current.start),
                  )
                : current?.kind === "setdown"
                  ? b
                  : a
              : { x: (a.x + b.x) / 2, y: lane };
            const labelPoint = s.movement
              ? along(points, 0.45)
              : { x: a.x + 18 + i * 18, y: lane };
            const active = j.id === selected,
              proposed = preview?.job_id === j.id;

            return (
              <g
                key={j.id}
                {...pick(j.id)}
                aria-label={`Step ${i + 1}: ${cargoName(j.container_id)}, ${j.source_id} to ${j.target_id}, ${j.status}`}
              >
                <path
                  d={path}
                  stroke="transparent"
                  strokeWidth="20"
                  fill="none"
                />
                <path
                  d={path}
                  stroke={color}
                  strokeWidth={active ? 5 : 3}
                  strokeDasharray={
                    proposed
                      ? "4 6"
                      : j.status === "queued"
                        ? "10 5"
                        : undefined
                  }
                  opacity={j.status === "completed" ? 0.45 : 1}
                  fill="none"
                  markerEnd={`url(#${uid}arrow${i % routeColors.length})`}
                />
                <circle
                  cx={labelPoint.x + i * 5}
                  cy={labelPoint.y + i * 5}
                  r="13"
                  fill={color}
                />
                <text
                  x={labelPoint.x + i * 5}
                  y={labelPoint.y + i * 5 + 5}
                  textAnchor="middle"
                  fill="#132e36"
                  fontWeight="700"
                >
                  {i + 1}
                </text>
                {j.status === "running" && (
                  <g>
                    <circle
                      cx={marker.x}
                      cy={marker.y}
                      r="9"
                      fill="#fff"
                      stroke={color}
                      strokeWidth="4"
                    />
                    <title>Modeled stage position; not GPS</title>
                  </g>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <footer>
        {routes.map((j, i) => (
          <button
            key={j.id}
            onClick={() => select(j.id)}
            aria-pressed={j.id === selected}
          >
            <span style={{ background: routeColors[i % 4] }}>{i + 1}</span>
            {cargoName(j.container_id)} · {j.source_id} → {j.target_id}
            <small>
              {preview?.job_id === j.id
                ? "Preview"
                : j.status === "queued"
                  ? mode === "proposal"
                    ? "Proposed"
                    : mode === "approved"
                      ? s.schedule?.rows.some((r) => r.job_id === j.id)
                        ? "Booked"
                        : "Unbooked"
                      : "Instructed"
                  : j.status}
            </small>
          </button>
        ))}
      </footer>
    </section>
  );
}
