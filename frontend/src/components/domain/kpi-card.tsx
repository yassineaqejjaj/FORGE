import * as React from "react";
import Link from "next/link";

import { DeltaIndicator, type DeltaKind } from "@/components/domain/delta-indicator";
import { Sparkline } from "@/components/domain/sparkline";
import { Skeleton } from "@/components/ui/skeleton";
import type { Tone } from "@/lib/enums";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

export interface KpiDelta {
  /** Signed delta vs the previous period / baseline. */
  value: number | null | undefined;
  unit?: string;
  digits?: number;
  kind?: DeltaKind;
  higherIsBetter?: boolean;
  /** e.g. "vs 30 j précédents". */
  label?: string;
}

export interface KpiCardProps {
  label: React.ReactNode;
  /** Formatted value (use the format helpers / CostDisplay…). */
  value: React.ReactNode;
  /** Small unit after the value ("/ 100", "runs"). */
  unit?: React.ReactNode;
  /** Lucide icon element. */
  icon?: React.ReactNode;
  /** Tone of the icon chip (default brand orange). */
  tone?: Tone;
  delta?: KpiDelta;
  /** Trend values (chronological) rendered as a sparkline. */
  trend?: ReadonlyArray<number | null | undefined>;
  /** Fixed domain for the sparkline (e.g. [0, 100]). */
  trendDomain?: [number, number];
  /** Secondary line under the value. */
  hint?: React.ReactNode;
  loading?: boolean;
  /** Makes the whole card a link. */
  href?: string;
  className?: string;
  children?: React.ReactNode;
}

/** Dashboard KPI tile: label, value (+unit), signed delta, optional sparkline. */
export function KpiCard({
  label,
  value,
  unit,
  icon,
  tone = "orange",
  delta,
  trend,
  trendDomain,
  hint,
  loading = false,
  href,
  className,
  children,
}: KpiCardProps) {
  const t = toneClasses(tone);
  const body = (
    <div
      className={cn(
        "group relative flex h-full flex-col gap-3 overflow-hidden rounded-xl border border-border bg-card p-4 shadow-panel",
        href && "transition-[border-color,box-shadow] hover:border-border-strong hover:shadow-md",
        className,
      )}
      aria-busy={loading || undefined}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[12.5px] font-medium text-muted-foreground">{label}</p>
        {icon ? (
          <span className={cn("flex size-7 items-center justify-center rounded-lg ring-1 ring-inset [&_svg]:size-3.5", t.soft)} aria-hidden>
            {icon}
          </span>
        ) : null}
      </div>
      <div className="flex items-end justify-between gap-3">
        <div className="grid min-w-0 gap-1">
          {loading ? (
            <Skeleton className="h-7 w-24" />
          ) : (
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="text-2xl font-semibold tracking-tight tabular-nums text-foreground">{value}</span>
              {unit ? <span className="text-xs font-medium text-muted-foreground">{unit}</span> : null}
              {delta ? (
                <span className="inline-flex items-center gap-1">
                  <DeltaIndicator
                    value={delta.value}
                    unit={delta.unit}
                    digits={delta.digits}
                    kind={delta.kind}
                    higherIsBetter={delta.higherIsBetter}
                  />
                  {delta.label ? <span className="text-xs text-muted-foreground">{delta.label}</span> : null}
                </span>
              ) : null}
            </div>
          )}
          {hint ? loading ? <Skeleton className="h-3 w-32" /> : <div className="text-xs text-muted-foreground">{hint}</div> : null}
        </div>
        {trend && !loading ? <Sparkline data={trend} domain={trendDomain} width={88} height={30} className="mb-0.5" /> : null}
      </div>
      {children}
    </div>
  );

  if (href) {
    return (
      <Link href={href} className="block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {body}
      </Link>
    );
  }
  return body;
}

/** Skeleton grid placeholder for a row of KPI cards. */
export function KpiCardSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("flex h-full flex-col gap-3 rounded-xl border border-border bg-card p-4 shadow-panel", className)} aria-hidden>
      <div className="flex items-start justify-between">
        <Skeleton className="h-3.5 w-24" />
        <Skeleton className="size-7 rounded-lg" />
      </div>
      <div className="flex items-end justify-between gap-3">
        <div className="grid gap-2">
          <Skeleton className="h-7 w-20" />
          <Skeleton className="h-3 w-28" />
        </div>
        <Skeleton className="h-7 w-20" />
      </div>
    </div>
  );
}
