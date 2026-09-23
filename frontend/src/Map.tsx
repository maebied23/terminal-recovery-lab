import { relatedJobs, contextIds } from "./relationships";
import { useState } from "react";
import { Minus, Plus, Maximize2 } from "lucide-react";
import type { State } from "./types";
import { clock } from "./types";
export function TerminalMap({
  s,
  selected,
  select,
  flow,
}: {
  s: State;
  selected: string;
  select: (id: string) => void;
  flow: string;
}) {
  const [zoom, setZoom] = useState(1);
  const context = contextIds(s, selected);
  const related = s.jobs.filter((j) => context.has(j.id));
  const relatedLocations = new Set(
    related.flatMap((j) => [j.source_id, j.target_id]),
  );
  const pick = (id: string) => ({
    onClick: () => select(id),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        select(id);
      }
    },
    tabIndex: 0,
    role: "button" as const,
    "aria-label": `Inspect ${id}`,
  });
  return (
    <div className="map-wrap">
      <div className="map-caption">
        <span className="live-dot" /> NORTHSTAR TERMINAL{" "}
        <span>Fictional layout · schematic</span>
      </div>
      <svg
        className="terminal-map"
        viewBox={`${550 - 550 / zoom} ${360 - 360 / zoom} ${1100 / zoom} ${720 / zoom}`}
        aria-label="Interactive terminal map"
      >
        <defs>
          <pattern
            id="water"
            width="35"
            height="20"
            patternUnits="userSpaceOnUse"
          >
            <path d="M0 10h12" stroke="#213e4d" strokeWidth="1" />
          </pattern>
          <pattern
            id="land"
            width="20"
            height="20"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r=".6" fill="#38454d" />
          </pattern>
          <filter id="shadow">
            <feDropShadow dx="0" dy="5" stdDeviation="5" floodOpacity=".3" />
          </filter>
        </defs>
        <rect width="1100" height="720" fill="#192730" />
        <rect width="1100" height="170" fill="#152d3c" />
        <rect width="1100" height="170" fill="url(#water)" />
        <text x="40" y="52" className="map-water-label">
          NORTH CHANNEL
        </text>
        <path d="M1020 70v-30m-8 9 8-9 8 9" stroke="#91a9b2" fill="none" />
        <text x="1015" y="95" className="map-small">
          N
        </text>
        <rect x="35" y="173" width="1030" height="514" rx="10" fill="#29363e" />
        <rect x="35" y="173" width="1030" height="514" fill="url(#land)" />
        <path d="M45 175H1055" stroke="#bbc2ba" strokeWidth="5" />
        <path
          d="M75 222H1030M75 388H1030M75 552H560M92 220V650M1030 222V655"
          fill="none"
          stroke="#1b282f"
          strokeWidth="25"
        />
        <path
          d="M75 222H1030M75 388H1030M75 552H560M92 220V650M1030 222V655"
          fill="none"
          stroke="#66727a"
          strokeWidth="1"
          strokeDasharray="9 9"
        />
        {[0, 1].map((i) => {
          const co = s.commitments.find(
            (c) => c.kind === "vessel" && c.location_id === `VESSEL-${i + 1}`,
          )!;
          const x = i ? 625 : 115;
          const onboard = s.containers.filter(
            (c) => c.location_id === co.location_id,
          );
          return (
            <g
              key={co.id}
              {...pick(co.id)}
              className={`map-click ${selected === co.id ? "chosen" : ""}`}
              opacity={
                co.status === "departed" ? 0.3 : s.minute < co.arrival ? 0.5 : 1
              }
            >
              <path
                d={`M${x} 70h290l35 35-35 35H${x}l-15-35z`}
                fill="#dae0d9"
                stroke={selected === co.id ? "#5eeee0" : "#6d929f"}
                strokeWidth="2"
                filter="url(#shadow)"
              />
              {onboard.slice(0, 12).map((cargo, k) => (
                <g
                  key={cargo.id}
                  {...pick(cargo.id)}
                  onClick={(e) => {
                    e.stopPropagation();
                    select(cargo.id);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      e.stopPropagation();
                      select(cargo.id);
                    }
                  }}
                >
                  <rect
                    x={x + 12 + (k % 3) * 74}
                    y={77 + Math.floor(k / 3) * 14}
                    width="70"
                    height="12"
                    rx="2"
                    fill={selected === cargo.id ? "#5eeee0" : "#376766"}
                  />
                  <text
                    x={x + 47 + (k % 3) * 74}
                    y={86 + Math.floor(k / 3) * 14}
                    textAnchor="middle"
                    fill="white"
                    fontSize="8"
                  >
                    {cargo.id}
                  </text>
                  <title>
                    {cargo.id} · {cargo.flow} · {cargo.commitment_id}
                  </title>
                </g>
              ))}
              <rect
                x={x + 242}
                y="88"
                width="27"
                height="34"
                rx="2"
                fill="#9eafa9"
              />
              <text x={x + 20} y="62" className="map-label">
                MV {co.id}{" "}
                <tspan className="map-muted"> / BERTH 0{i + 1}</tspan>
              </text>
              <text x={x + 8} y="158" className="map-small">
                {co.status === "departed"
                  ? "DEPARTED"
                  : s.minute < co.arrival
                    ? `DUE ${clock(co.arrival)}`
                    : `${onboard.length} ON BOARD · UNTIL ${clock(co.cutoff)}`}
              </text>
            </g>
          );
        })}
        {["A", "B", "C", "D", "E", "F"].map((block, i) => {
          const locs = s.locations.filter((l) => l.block === block),
            x = 145 + (i % 3) * 225,
            y = 255 + Math.floor(i / 3) * 170;
          const count = s.containers.filter((c) =>
            locs.some((l) => l.id === c.location_id),
          ).length;
          return (
            <g key={block}>
              <rect
                x={x - 10}
                y={y - 12}
                width="202"
                height="125"
                rx="5"
                fill="#324149"
                stroke="#4a565b"
              />
              <text x={x} y={y - 23} className="map-label">
                BLOCK {block} <tspan className="map-muted">{count}/32</tspan>
              </text>
              {locs.map((l) => {
                const cargo = s.containers
                  .filter((c) => c.location_id === l.id)
                  .sort((a, b) => a.tier - b.tier);
                const highlight =
                  relatedLocations.has(l.id) ||
                  selected === l.id ||
                  cargo.some((c) => c.id === selected);
                return (
                  <g key={l.id} {...pick(l.id)} className="map-click">
                    <rect
                      x={l.x - 4}
                      y={l.y - 3}
                      width="34"
                      height="81"
                      rx="3"
                      fill={highlight ? "#294f50" : "#233138"}
                      stroke={highlight ? "#64ddd1" : "#5b6668"}
                      strokeWidth={highlight ? 2 : 1}
                    />
                    {cargo.map((c, k) => {
                      const relevant = flow === "all" || c.flow.includes(flow);
                      return (
                        <g
                          key={c.id}
                          {...pick(c.id)}
                          onClick={(e) => {
                            e.stopPropagation();
                            select(c.id);
                          }}
                        >
                          <rect
                            x={l.x}
                            y={l.y + 3 + k * 9}
                            width="26"
                            height="7"
                            rx="1"
                            opacity={relevant ? 1 : 0.18}
                            fill={
                              c.id === selected
                                ? "#82fff0"
                                : !c.released
                                  ? "#dd9574"
                                  : c.flow === "storage"
                                    ? "#647e85"
                                    : c.flow.includes("rail")
                                      ? "#ad9b6d"
                                      : "#4ba69d"
                            }
                          />
                          <title>
                            {c.id} · tier {c.tier} · {c.flow}
                          </title>
                        </g>
                      );
                    })}
                    <text x={l.x + 4} y={l.y + 94} className="map-small">
                      {l.id}
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}
        <g {...pick("GATE-IN")} className="map-click">
          <rect x="60" y="594" width="120" height="60" rx="4" fill="#4c5757" />
          <path
            d="M80 600v47m25-47v47m25-47v47m25-47v47"
            stroke="#a7b1a9"
            strokeWidth="2"
          />
          <text x="61" y="677" className="map-label">
            ROAD GATE
          </text>
        </g>
        <g {...pick("ROAD-AM")} className="map-click">
          <rect x="240" y="580" width="215" height="72" rx="4" fill="#303f43" />
          {Array.from(
            {
              length: Math.min(
                10,
                s.containers.filter((c) => c.location_id === "GATE-IN").length,
              ),
            },
            (_, i) => (
              <g
                key={i}
                transform={`translate(${250 + (i % 5) * 39} ${589 + Math.floor(i / 5) * 29})`}
              >
                <rect width="25" height="13" rx="2" fill="#af9770" />
                <rect
                  x="25"
                  y="3"
                  width="8"
                  height="10"
                  rx="2"
                  fill="#cbd0c9"
                />
              </g>
            ),
          )}
          <text x="240" y="675" className="map-label">
            TRUCK EXCHANGE
          </text>
        </g>
        {s.commitments
          .filter((c) => c.kind === "rail")
          .map((co, i) => {
            const y = s.locations.find((l) => l.id === co.location_id)!.y + 25;
            const count = s.containers.filter(
              (c) => c.location_id === co.location_id,
            ).length;
            return (
              <g
                key={co.id}
                {...pick(co.id)}
                className="map-click"
                opacity={co.status === "departed" ? 0.45 : 1}
              >
                <path
                  d={`M560 ${y}H1010m-450 12h450`}
                  stroke="#9b9e91"
                  strokeWidth="2"
                />
                {Array.from({ length: 24 }, (_, k) => (
                  <path
                    key={k}
                    d={`M${565 + k * 18} ${y - 4}v20`}
                    stroke="#676f69"
                    strokeWidth="2"
                  />
                ))}
                {Array.from({ length: 12 }, (_, k) => (
                  <rect
                    key={k}
                    x={570 + k * 34}
                    y={y - 6}
                    width="30"
                    height="18"
                    rx="2"
                    fill={k < count ? "#c0a36a" : "#4a5758"}
                    stroke={selected === co.id ? "#66e2d5" : "#879183"}
                  />
                ))}
                <text x="565" y={y - 15} className="map-label">
                  {co.id}{" "}
                  <tspan className="map-muted">
                    {count}/{co.capacity} · {clock(co.cutoff)}
                  </tspan>
                </text>
              </g>
            );
          })}
        {related
          .filter(
            (j) =>
              j.status !== "completed" &&
              (s.jobs.some((x) => x.id === selected) ||
                s.containers.some(
                  (c) => c.id === selected || c.visit_id === selected,
                )),
          )
          .map((j) => {
            const a = s.locations.find((l) => l.id === j.source_id)!,
              b = s.locations.find((l) => l.id === j.target_id)!;
            return (
              <path
                key={j.id}
                d={`M${a.x + 12} ${a.y + 30} Q${(a.x + b.x) / 2} ${Math.min(a.y, b.y) - 45} ${b.x + 12} ${b.y + 30}`}
                stroke="#72e1d1"
                fill="none"
                strokeWidth="2"
                strokeDasharray="6 5"
                opacity=".7"
              />
            );
          })}
        {s.equipment.map((e) => {
          const j = s.jobs.find((j) => j.id === e.job_id);
          let x = e.x,
            y = e.y;
          if (j && e.kind === "tractor") {
            const a = s.locations.find((l) => l.id === j.source_id)!,
              b = s.locations.find((l) => l.id === j.target_id)!;
            const f = Math.max(
              0,
              Math.min(1, 1 - j.remaining / (j.duration * 1.2 + 1)),
            );
            x = a.x + (b.x - a.x) * f;
            y = a.y + (b.y - a.y) * f + 20;
          }
          return (
            <g
              key={e.id}
              {...pick(e.id)}
              transform={`translate(${x},${y})`}
              className="map-click equipment-marker"
            >
              <circle
                r={context.has(e.id) ? 23 : 18}
                fill="#17252d"
                stroke={
                  e.status === "failed"
                    ? "#f19176"
                    : e.job_id
                      ? "#6fdfcd"
                      : "#a1b0b4"
                }
                strokeWidth="2"
              />
              {e.kind === "quay" ? (
                <path
                  d="M-10 9V-12H15M-5 9V-12m0 5h15v12"
                  stroke="#d1b774"
                  fill="none"
                  strokeWidth="3"
                />
              ) : e.kind === "tractor" ? (
                <path d="M-11-5h14v11h-14zm14 3h7v8H3" fill="#bac6bc" />
              ) : (
                <path
                  d="M-10 9V-9h20V9M-10-3h20M0-9v14"
                  stroke="#d1b774"
                  fill="none"
                  strokeWidth="3"
                />
              )}
              <text
                y={e.kind === "tractor" ? -24 : 34}
                textAnchor="middle"
                className="map-equipment"
              >
                {e.id}
                {e.status === "failed" ? " !" : ""}
              </text>
            </g>
          );
        })}
        <text x="45" y="712" className="map-small">
          SCHEMATIC · NOT FOR NAVIGATION
        </text>
        <text x="840" y="712" className="map-small">
          STATE REVISION {s.revision}
        </text>
      </svg>
      <div className="map-legend">
        <span>
          <i style={{ background: "#4ba69d" }} />
          Active cargo
        </span>
        <span>
          <i style={{ background: "#ad9b6d" }} />
          Rail export
        </span>
        <span>
          <i style={{ background: "#dd9574" }} />
          Authority hold
        </span>
        <span>
          <i style={{ background: "#647e85" }} />
          Stored inventory
        </span>
      </div>
      <div className="map-zoom">
        <button
          aria-label="Zoom in"
          onClick={() => setZoom(Math.min(1.7, zoom + 0.2))}
        >
          <Plus size={16} />
        </button>
        <button
          aria-label="Zoom out"
          onClick={() => setZoom(Math.max(1, zoom - 0.2))}
        >
          <Minus size={16} />
        </button>
        <button aria-label="Reset map zoom" onClick={() => setZoom(1)}>
          <Maximize2 size={16} />
        </button>
      </div>
    </div>
  );
}
