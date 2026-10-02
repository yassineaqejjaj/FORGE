"use client";

import * as React from "react";
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartTooltipContent,
  chartAxisProps,
  chartCursor,
  chartGridProps,
  chartLineProps,
} from "@/components/ui/chart";
import { formatDateLong, formatDayShort } from "@/lib/format";

export interface TrendChartProps<T extends { date: string }> {
  data: ReadonlyArray<T>;
  dataKey: keyof T & string;
  /** Series name (tooltip) and accessible label. */
  name: string;
  color: string;
  valueFormatter: (value: number) => string;
  tickFormatter?: (value: number) => string;
  domain?: [number | "auto", number | "auto"];
  height?: number;
}

/** Single-series daily line chart (one y-axis, crosshair tooltip, gaps where no run was evaluated). */
export function TrendChart<T extends { date: string }>({
  data,
  dataKey,
  name,
  color,
  valueFormatter,
  tickFormatter,
  domain = ["auto", "auto"],
  height = 180,
}: TrendChartProps<T>) {
  const points = data.filter((d) => typeof d[dataKey] === "number").length;
  if (points === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-dashed border-border text-xs text-muted-foreground"
        style={{ height }}
      >
        Aucune donnée sur la période
      </div>
    );
  }
  return (
    <ChartContainer height={height} label={`${name} par jour`}>
      <LineChart data={[...data]} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid {...chartGridProps} />
        <XAxis dataKey="date" {...chartAxisProps} tickFormatter={(v: string) => formatDayShort(v)} minTickGap={24} />
        <YAxis {...chartAxisProps} width={52} domain={domain} tickFormatter={tickFormatter ?? valueFormatter} />
        <Tooltip
          cursor={chartCursor}
          content={
            <ChartTooltipContent
              labelFormatter={(l) => formatDateLong(String(l))}
              valueFormatter={(v) => valueFormatter(v)}
            />
          }
        />
        <Line
          dataKey={dataKey}
          name={name}
          stroke={color}
          {...chartLineProps}
          dot={points <= 12 ? { r: 4, strokeWidth: 2, stroke: "var(--card)", fill: color } : false}
          connectNulls
        />
      </LineChart>
    </ChartContainer>
  );
}
