import * as React from "react";

import { DIMENSION_META, DIMENSIONS } from "@/lib/enums";
import { cn } from "@/lib/utils";

const SIZE = 360;
const CENTER = SIZE / 2;
const RADIUS = 118;
const RINGS = [0.25, 0.5, 0.75, 1];
// Illustrative values only (decorative hero on the login page).
const BASELINE = [0.62, 0.58, 0.55, 0.7, 0.5, 0.66, 0.6, 0.57];
const CANDIDATE = [0.82, 0.74, 0.7, 0.86, 0.68, 0.6, 0.72, 0.78];

function point(index: number, ratio: number): [number, number] {
  const angle = -Math.PI / 2 + (index * 2 * Math.PI) / DIMENSIONS.length;
  return [CENTER + Math.cos(angle) * RADIUS * ratio, CENTER + Math.sin(angle) * RADIUS * ratio];
}

function polygon(values: number[]): string {
  return values.map((v, i) => point(i, v).map((n) => n.toFixed(1)).join(",")).join(" ");
}

/** Decorative "baseline vs candidate" radar used on the login brand panel. */
export function ForgeHero({ className }: { className?: string }) {
  const uid = React.useId().replace(/:/g, "");
  return (
    <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className={cn("h-auto w-full", className)} aria-hidden>
      <defs>
        <radialGradient id={`glow-${uid}`} cx="50%" cy="50%" r="50%">
          <stop offset="0" stopColor="#F97316" stopOpacity="0.22" />
          <stop offset="1" stopColor="#F97316" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`cand-${uid}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#FDBA74" stopOpacity="0.55" />
          <stop offset="1" stopColor="#EA580C" stopOpacity="0.3" />
        </linearGradient>
      </defs>
      <circle cx={CENTER} cy={CENTER} r={RADIUS * 1.35} fill={`url(#glow-${uid})`} />
      {RINGS.map((r) => (
        <polygon
          key={r}
          points={polygon(DIMENSIONS.map(() => r))}
          fill="none"
          stroke="#FFFFFF"
          strokeOpacity={r === 1 ? 0.16 : 0.08}
        />
      ))}
      {DIMENSIONS.map((d, i) => {
        const [x, y] = point(i, 1);
        const [lx, ly] = point(i, 1.2);
        return (
          <g key={d}>
            <line x1={CENTER} y1={CENTER} x2={x} y2={y} stroke="#FFFFFF" strokeOpacity={0.08} />
            <text
              x={lx}
              y={ly}
              fill="#A8A29E"
              fontSize="10.5"
              fontWeight="500"
              textAnchor={Math.abs(lx - CENTER) < 4 ? "middle" : lx > CENTER ? "start" : "end"}
              dominantBaseline="middle"
            >
              {DIMENSION_META[d].short}
            </text>
          </g>
        );
      })}
      <polygon points={polygon(BASELINE)} fill="#A8A29E" fillOpacity={0.1} stroke="#A8A29E" strokeOpacity={0.6} strokeDasharray="4 4" />
      <polygon points={polygon(CANDIDATE)} fill={`url(#cand-${uid})`} stroke="#FB923C" strokeWidth={2} strokeLinejoin="round" />
      {CANDIDATE.map((v, i) => {
        const [x, y] = point(i, v);
        return <circle key={i} cx={x} cy={y} r={3} fill="#FFF7ED" stroke="#F97316" strokeWidth={1.5} />;
      })}
    </svg>
  );
}
