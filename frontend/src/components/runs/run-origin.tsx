"use client";

import Link from "next/link";

import { RunOriginBadge } from "@/components/domain/enum-badge";
import { EnumIcon } from "@/components/domain/enum-icon";
import { getMeta, RUN_ORIGIN_META } from "@/lib/enums";
import { cn } from "@/lib/utils";

export interface RunOriginProps {
  origin: string;
  benchmarkId?: string | null;
  benchmarkExecutionId?: string | null;
  experimentId?: string | null;
  experimentName?: string | null;
  arm?: string | null;
  className?: string;
}

/** Origin of a run (ad hoc / benchmark / experiment / observed) with a link to its parent when there is one. */
export function RunOrigin({ origin, benchmarkId, benchmarkExecutionId, experimentId, experimentName, arm, className }: RunOriginProps) {
  const meta = getMeta(RUN_ORIGIN_META, origin);
  let href: string | null = null;
  let title: string = meta.label;
  if (origin === "experiment" && experimentId) {
    href = `/experiments/${experimentId}`;
    title = experimentName ? `Expérience « ${experimentName} »` : "Ouvrir l'expérience";
  } else if (origin === "benchmark" && benchmarkId) {
    href = `/benchmarks/${benchmarkId}`;
    title = "Ouvrir le benchmark";
  } else if (origin === "benchmark" && benchmarkExecutionId) {
    href = `/runs?benchmark_execution_id=${benchmarkExecutionId}`;
    title = "Runs de cette exécution de benchmark";
  }
  if (!href) return <RunOriginBadge value={origin} className={className} />;
  return (
    <Link
      href={href}
      title={title}
      onClick={(e) => e.stopPropagation()}
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-md px-1.5 text-[11px] font-medium text-primary ring-1 ring-inset ring-border hover:bg-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-3",
        className,
      )}
    >
      <EnumIcon name={meta.icon} />
      {meta.label}
      {arm ? <span className="text-muted-foreground">· {arm === "baseline" ? "référence" : "candidate"}</span> : null}
    </Link>
  );
}
