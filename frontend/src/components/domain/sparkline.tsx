import * as React from "react";

import { cn } from "@/lib/utils";

export interface SparklineProps {
  /** Values in chronological order (null = gap). */
  data: ReadonlyArray<number | null | undefined>;
  width?: number;
  height?: number;
  /** Stroke colour (CSS). Default: brand. */
  color?: string;
  /** Fill the area under the line. */
  area?: boolean;
  /** Fixed domain (e.g. [0, 100] for scores); default: data min/max. */
  domain?: [number, number];
  /** Highlight the last point. */
  showLast?: boolean;
  /** Stretch to the container width (height stays fixed). */
  fluid?: boolean;
  /** Accessible summary; the sparkline is decorative when omitted. */
  label?: string;
  className?: string;
}

/** Tiny inline trend line (pure SVG, no axes). */
export function Sparkline({
  data,
  width = 96,
  height = 28,
  color = "var(--brand)",
  area = true,
  domain,
  showLast = true,
  fluid = false,
  label,
  className,
}: SparklineProps) {
  const uid = React.useId().replace(/:/g, "");
  const values = data.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : null));
  const numeric = values.filter((v): v is number => v !== null);
  if (numeric.length < 2) {
    return <span className={cn("inline-block text-xs text-subtle-foreground", className)} style={{ width: fluid ? "100%" : width, height }} aria-hidden />;
  }
  const [min, max] = domain ?? [Math.min(...numeric), Math.max(...numeric)];
  const span = max - min || 1;
  const pad = 2;
  const stepX = (width - pad * 2) / Math.max(1, values.length - 1);
  const y = (v: number) => pad + (height - pad * 2) * (1 - (v - min) / span);

  const segments: Array<Array<[number, number]>> = [];
  let current: Array<[number, number]> = [];
  values.forEach((v, i) => {
    if (v === null) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push([pad + i * stepX, y(v)]);
    }
  });
  if (current.length) segments.push(current);

  const line = segments.map((seg) => seg.map(([px, py], i) => `${i === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ")).join(" ");
  const areaPath = segments
    .filter((seg) => seg.length > 1)
    .map((seg) => {
      const first = seg[0]!;
      const last = seg[seg.length - 1]!;
      return `M${first[0].toFixed(1)},${height} ${seg.map(([px, py]) => `L${px.toFixed(1)},${py.toFixed(1)}`).join(" ")} L${last[0].toFixed(1)},${height} Z`;
    })
    .join(" ");
  const lastSeg = segments[segments.length - 1];
  const lastPoint = lastSeg?.[lastSeg.length - 1];

  return (
    <svg
      width={fluid ? "100%" : width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={cn("shrink-0 overflow-visible", className)}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {area ? (
        <>
          <defs>
            <linearGradient id={`spark-${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={color} stopOpacity={0.22} />
              <stop offset="1" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <path d={areaPath} fill={`url(#spark-${uid})`} />
        </>
      ) : null}
      <path d={line} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      {showLast && lastPoint ? <circle cx={lastPoint[0]} cy={lastPoint[1]} r={2.25} fill={color} /> : null}
    </svg>
  );
}
