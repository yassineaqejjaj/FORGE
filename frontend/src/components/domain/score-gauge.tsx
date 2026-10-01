import * as React from "react";

import { formatScore100 } from "@/lib/format";
import { clamp100, SCORE_BAND_META, scoreBand, type ScoreThresholds } from "@/lib/scores";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

export interface ScoreGaugeProps {
  /** Score on the 0–100 scale (null → empty gauge with "—"). */
  value: number | null | undefined;
  /** Caption under the value (e.g. "Composite"). */
  label?: React.ReactNode;
  /** `pass_threshold` of the evaluation configuration, drawn as a tick (0–100). */
  passThreshold?: number | null;
  /** `run.passed` from the API. */
  passed?: boolean | null;
  /** `run.gate_failed` from the API. */
  gateFailed?: boolean | null;
  thresholds?: ScoreThresholds;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const DIMENSIONS = {
  sm: { box: 64, stroke: 6, font: "text-base", caption: "text-[10px]" },
  md: { box: 112, stroke: 9, font: "text-2xl", caption: "text-[11px]" },
  lg: { box: 156, stroke: 11, font: "text-4xl", caption: "text-xs" },
} as const;

// 270° arc opening at the bottom.
const SWEEP = 270;
const START = 135;

function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const rad = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

function arcPath(cx: number, cy: number, r: number, fromDeg: number, toDeg: number): string {
  const [x1, y1] = polar(cx, cy, r, fromDeg);
  const [x2, y2] = polar(cx, cy, r, toDeg);
  const large = toDeg - fromDeg > 180 ? 1 : 0;
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

/** Circular 0–100 gauge (composite score) with the FORGE colour scale and an optional pass-threshold tick. */
export function ScoreGauge({ value, label, passThreshold, passed, gateFailed, thresholds, size = "md", className }: ScoreGaugeProps) {
  const d = DIMENSIONS[size];
  const valid = typeof value === "number" && Number.isFinite(value);
  const v = valid ? clamp100(value) : 0;
  const band = valid ? scoreBand(v, thresholds) : null;
  const tone = gateFailed ? "red" : band ? SCORE_BAND_META[band].tone : "neutral";
  const t = toneClasses(tone);
  const cx = d.box / 2;
  const r = cx - d.stroke / 2 - 1;
  const end = START + (SWEEP * v) / 100;
  const text = valid ? formatScore100(v) : "—";
  const status =
    gateFailed ? "Garde-fou en échec" : passed === true ? "Réussi" : passed === false ? "Sous le seuil" : band ? SCORE_BAND_META[band].label : null;
  // Short caption inside the ring (the full status stays in aria-valuetext).
  const caption = gateFailed ? "Garde-fou" : status;
  const tick =
    typeof passThreshold === "number" && Number.isFinite(passThreshold)
      ? START + (SWEEP * clamp100(passThreshold)) / 100
      : null;

  return (
    <div
      className={cn("relative inline-grid shrink-0 place-items-center", className)}
      style={{ width: d.box, height: d.box }}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={valid ? v : undefined}
      aria-valuetext={valid ? `${text} sur 100${status ? `, ${status}` : ""}` : "Non disponible"}
      aria-label={typeof label === "string" ? label : "Score"}
    >
      <svg width={d.box} height={d.box} viewBox={`0 0 ${d.box} ${d.box}`} className="absolute inset-0" aria-hidden>
        <path
          d={arcPath(cx, cx, r, START, START + SWEEP)}
          fill="none"
          strokeWidth={d.stroke}
          strokeLinecap="round"
          className="stroke-muted"
        />
        {valid && v > 0 ? (
          <path
            d={arcPath(cx, cx, r, START, Math.max(START + 0.5, end))}
            fill="none"
            strokeWidth={d.stroke}
            strokeLinecap="round"
            stroke="currentColor"
            className={t.text}
          />
        ) : null}
        {tick !== null ? (
          (() => {
            const [x1, y1] = polar(cx, cx, r - d.stroke / 2 - 2, tick);
            const [x2, y2] = polar(cx, cx, r + d.stroke / 2 + 2, tick);
            return <line x1={x1} y1={y1} x2={x2} y2={y2} strokeWidth={2} strokeLinecap="round" className="stroke-foreground/70" />;
          })()
        ) : null}
      </svg>
      <div className="relative grid justify-items-center leading-none">
        <span className={cn("font-semibold tracking-tight tabular-nums text-foreground", d.font)}>{text}</span>
        {label ? <span className={cn("mt-1 font-medium text-muted-foreground", d.caption)}>{label}</span> : null}
        {caption && size !== "sm" ? <span className={cn("mt-1 font-medium", d.caption, t.text)}>{caption}</span> : null}
      </div>
    </div>
  );
}
