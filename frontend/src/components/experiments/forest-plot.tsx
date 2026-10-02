"use client";

import * as React from "react";

import type { MetricComparison } from "@/lib/api/experiments";
import { VERDICT_META, getMeta } from "@/lib/enums";
import { formatInterval, formatSigned } from "@/lib/format";

const VERDICT_COLORS: Record<string, string> = {
  better: "var(--color-emerald-600, #059669)",
  worse: "var(--color-red-600, #dc2626)",
  equivalent: "var(--color-blue-600, #2563eb)",
  inconclusive: "var(--muted-foreground)",
};

export interface ForestPlotProps {
  rows: MetricComparison[];
  /** Equivalence margin (± points) from `statistics.equivalence_margin`. */
  equivalenceMargin?: number;
  className?: string;
}

/**
 * Forest plot of paired deltas (candidate − baseline, points) with their 95 % CI.
 * Shaded band = equivalence margin; vertical line = no difference. Pure rendering of API values.
 */
export function ForestPlot({ rows, equivalenceMargin, className }: ForestPlotProps) {
  const plotted = rows.filter((r) => typeof r.delta === "number");
  if (!plotted.length) {
    return <p className="py-6 text-center text-[13px] text-muted-foreground">Aucun delta calculé pour l&apos;instant.</p>;
  }
  const extent = Math.max(
    equivalenceMargin ?? 0,
    ...plotted.flatMap((r) => [Math.abs(r.ci_low ?? r.delta ?? 0), Math.abs(r.ci_high ?? r.delta ?? 0), Math.abs(r.delta ?? 0)]),
    1,
  );
  const max = Math.ceil(extent * 1.15);
  const labelW = 150;
  const valueW = 150;
  const plotW = 420;
  const rowH = 30;
  const top = 22;
  const width = labelW + plotW + valueW;
  const height = top + plotted.length * rowH + 8;
  const x = (v: number) => labelW + ((v + max) / (2 * max)) * plotW;
  const ticks = [-max, -max / 2, 0, max / 2, max];

  return (
    <div className={className}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full"
        role="img"
        aria-label={`Graphique en forêt des deltas : ${plotted
          .map((r) => `${r.label} ${formatSigned(r.delta, { unit: "points" })} ${formatInterval(r.ci_low, r.ci_high)}`)
          .join(" ; ")}`}
      >
        {equivalenceMargin ? (
          <rect
            x={x(-equivalenceMargin)}
            y={top - 6}
            width={x(equivalenceMargin) - x(-equivalenceMargin)}
            height={plotted.length * rowH + 4}
            fill="var(--muted)"
            opacity={0.7}
            rx={4}
          />
        ) : null}
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={top - 6} y2={height - 4} stroke={t === 0 ? "var(--border-strong)" : "var(--chart-grid)"} strokeWidth={t === 0 ? 1.5 : 1} />
            <text x={x(t)} y={12} textAnchor="middle" fontSize={10} fill="var(--muted-foreground)">
              {formatSigned(t, { digits: 0 })}
            </text>
          </g>
        ))}
        {plotted.map((r, i) => {
          const y = top + i * rowH + rowH / 2 - 4;
          const color = VERDICT_COLORS[r.verdict] ?? "var(--muted-foreground)";
          const lo = typeof r.ci_low === "number" ? r.ci_low : (r.delta as number);
          const hi = typeof r.ci_high === "number" ? r.ci_high : (r.delta as number);
          const composite = r.key === "composite";
          return (
            <g key={r.key}>
              <text x={labelW - 10} y={y + 4} textAnchor="end" fontSize={12} fontWeight={composite ? 600 : 400} fill="var(--foreground)">
                {r.label}
              </text>
              <line x1={x(Math.max(-max, lo))} x2={x(Math.min(max, hi))} y1={y} y2={y} stroke={color} strokeWidth={2.5} strokeLinecap="round" />
              <line x1={x(Math.max(-max, lo))} x2={x(Math.max(-max, lo))} y1={y - 5} y2={y + 5} stroke={color} strokeWidth={1.5} />
              <line x1={x(Math.min(max, hi))} x2={x(Math.min(max, hi))} y1={y - 5} y2={y + 5} stroke={color} strokeWidth={1.5} />
              {composite ? (
                <rect x={x(r.delta as number) - 6} y={y - 6} width={12} height={12} transform={`rotate(45 ${x(r.delta as number)} ${y})`} fill={color} stroke="var(--card)" strokeWidth={1.5} />
              ) : (
                <circle cx={x(r.delta as number)} cy={y} r={5} fill={color} stroke="var(--card)" strokeWidth={1.5} />
              )}
              <text x={labelW + plotW + 12} y={y + 4} fontSize={11.5} fill="var(--foreground)" style={{ fontVariantNumeric: "tabular-nums" }}>
                {formatSigned(r.delta)}{" "}
                <tspan fill="var(--muted-foreground)">{formatInterval(r.ci_low, r.ci_high)}</tspan>
              </text>
            </g>
          );
        })}
      </svg>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-muted-foreground">
        {(["better", "equivalent", "worse", "inconclusive"] as const).map((v) => (
          <li key={v} className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ backgroundColor: VERDICT_COLORS[v] }} aria-hidden />
            {getMeta(VERDICT_META, v).label}
          </li>
        ))}
        {equivalenceMargin ? (
          <li className="flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-sm bg-muted" aria-hidden />
            Marge d&apos;équivalence ± {equivalenceMargin} pts
          </li>
        ) : null}
      </ul>
    </div>
  );
}
