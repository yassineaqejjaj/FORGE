"use client";

import * as React from "react";
import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, Tooltip } from "recharts";

import { dimensionMeta } from "@/components/domain/dimension-badge";
import { ChartContainer, ChartLegend } from "@/components/ui/chart";
import { DIMENSIONS, type Dimension } from "@/lib/enums";
import { formatScore100 } from "@/lib/format";
import { cn } from "@/lib/utils";

export type DimensionValues = Partial<Record<Dimension, number | null | undefined>>;

export interface DimensionRadarSeries {
  /** Legend / tooltip label ("v1.3 candidate"). */
  label: string;
  values: DimensionValues;
  /** CSS colour (defaults: first series brand orange, comparison neutral dashed). */
  color?: string;
  dashed?: boolean;
}

export interface DimensionRadarProps {
  /** Main series (e.g. the run or the candidate). */
  values: DimensionValues;
  label?: string;
  /** Optional comparison series (e.g. the baseline). */
  comparison?: DimensionValues;
  comparisonLabel?: string;
  /** Additional series (multi-agent benchmark), drawn after the comparison. */
  extraSeries?: DimensionRadarSeries[];
  /** Value scale of the inputs: 1 (0..1, API dimension scores) or 100 (0–100). Default 1. */
  scale?: 1 | 100;
  /** Axes to draw (default: the 8 dimensions). */
  dimensions?: readonly Dimension[];
  /** Hide axes that have no value in any series (e.g. robustness on a single run). Default true. */
  hideMissing?: boolean;
  height?: number;
  className?: string;
  /** Accessible description (defaults to a generated summary). */
  ariaLabel?: string;
}

const PRIMARY_COLOR = "var(--chart-1)";
const COMPARISON_COLOR = "var(--chart-axis)";

function toPercent(v: number | null | undefined, scale: 1 | 100): number | null {
  if (typeof v !== "number" || !Number.isFinite(v)) return null;
  return Math.max(0, Math.min(100, scale === 1 ? v * 100 : v));
}

interface Row {
  dimension: Dimension;
  axis: string;
  [series: string]: number | string | null;
}

/** Recharts radar of the evaluation dimensions (0–100), with an optional comparison series. */
export function DimensionRadar({
  values,
  label = "Scores",
  comparison,
  comparisonLabel = "Référence",
  extraSeries = [],
  scale = 1,
  dimensions = DIMENSIONS,
  hideMissing = true,
  height = 300,
  className,
  ariaLabel,
}: DimensionRadarProps) {
  const series: DimensionRadarSeries[] = [
    ...(comparison ? [{ label: comparisonLabel, values: comparison, color: COMPARISON_COLOR, dashed: true }] : []),
    ...extraSeries,
    { label, values, color: PRIMARY_COLOR },
  ];
  const keys = series.map((_, i) => `s${i}`);

  const axes = dimensions.filter(
    (d) => !hideMissing || series.some((s) => toPercent(s.values[d], scale) !== null),
  );

  const rows: Row[] = axes.map((d) => {
    const row: Row = { dimension: d, axis: dimensionMeta(d).short };
    series.forEach((s, i) => {
      row[keys[i]!] = toPercent(s.values[d], scale);
    });
    return row;
  });

  const summary =
    ariaLabel ??
    `Radar des dimensions — ${series
      .map((s) => `${s.label} : ${axes.map((d) => `${dimensionMeta(d).label} ${formatScore100(toPercent(s.values[d], scale))}`).join(", ")}`)
      .join(" ; ")}`;

  if (axes.length < 3) {
    return (
      <div className={cn("flex items-center justify-center rounded-lg border border-dashed border-border text-xs text-muted-foreground", className)} style={{ height }}>
        Pas assez de dimensions évaluées pour tracer le radar.
      </div>
    );
  }

  return (
    <div className={cn("grid gap-3", className)}>
      <ChartContainer height={height} label={summary}>
        <RadarChart data={rows} outerRadius="72%" margin={{ top: 8, right: 24, bottom: 8, left: 24 }}>
          <PolarGrid stroke="var(--chart-grid)" />
          <PolarAngleAxis dataKey="axis" tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} />
          <PolarRadiusAxis domain={[0, 100]} tickCount={5} tick={false} axisLine={false} />
          <Tooltip
            cursor={false}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0]?.payload as Row | undefined;
              if (!row) return null;
              return (
                <div className="min-w-40 rounded-lg border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-lg">
                  <p className="mb-1.5 font-medium text-foreground">{dimensionMeta(row.dimension).label}</p>
                  <ul className="grid gap-1">
                    {series.map((s, i) => {
                      const v = row[keys[i]!];
                      return (
                        <li key={s.label} className="flex items-center gap-2">
                          <span className="size-2.5 shrink-0 rounded-[3px]" style={{ backgroundColor: s.color ?? PRIMARY_COLOR }} aria-hidden />
                          <span className="flex-1 truncate text-muted-foreground">{s.label}</span>
                          <span className="font-medium tabular-nums text-foreground">
                            {typeof v === "number" ? formatScore100(v) : "n/d"}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            }}
          />
          {series.map((s, i) => (
            <Radar
              key={keys[i]}
              name={s.label}
              dataKey={keys[i]!}
              stroke={s.color ?? PRIMARY_COLOR}
              strokeWidth={s.dashed ? 1.5 : 2}
              strokeDasharray={s.dashed ? "4 4" : undefined}
              fill={s.color ?? PRIMARY_COLOR}
              fillOpacity={s.dashed ? 0.06 : 0.18}
              dot={s.dashed ? false : { r: 3, strokeWidth: 0, fill: s.color ?? PRIMARY_COLOR }}
              isAnimationActive={false}
            />
          ))}
        </RadarChart>
      </ChartContainer>
      {series.length > 1 ? (
        <ChartLegend className="justify-center" items={series.map((s) => ({ label: s.label, color: s.color ?? PRIMARY_COLOR }))} />
      ) : null}
    </div>
  );
}
