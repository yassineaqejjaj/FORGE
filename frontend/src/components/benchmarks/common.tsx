"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { CopyButton } from "@/components/ui/code-block";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { formatNumber, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Short content hash ("sha256:3d86…") with copy. */
export function HashChip({ hash, className }: { hash: string | null | undefined; className?: string }) {
  if (!hash) return <span className="text-subtle-foreground">—</span>;
  const short = hash.replace(/^sha256:/, "").slice(0, 10);
  return (
    <span className={cn("inline-flex items-center gap-0.5 font-mono text-[11.5px] text-muted-foreground", className)}>
      <SimpleTooltip content={hash}>
        <span tabIndex={0} className="rounded px-1 py-0.5 hover:bg-muted">
          {short}
        </span>
      </SimpleTooltip>
      <CopyButton value={hash} label="Copier l'empreinte" className="size-6" />
    </span>
  );
}

/** Progress of a batch of runs (done / total + failed). */
export function RunsProgress({
  completed,
  failed,
  total,
  active,
  className,
}: {
  completed: number;
  failed: number;
  total: number;
  active?: boolean;
  className?: string;
}) {
  const done = completed + failed;
  const ratio = total ? done / total : 0;
  return (
    <div className={cn("grid min-w-32 gap-1", className)}>
      <Progress
        value={ratio * 100}
        tone={failed > 0 && !active ? "amber" : active ? "orange" : "green"}
        size="sm"
        aria-label={`${done} runs terminés sur ${total}`}
      />
      <p className="flex items-center justify-between gap-2 text-[11.5px] tabular-nums text-muted-foreground">
        <span>
          {formatNumber(done, 0)} / {formatNumber(total, 0)} runs
          {failed > 0 ? <span className="text-red-700 dark:text-red-400"> · {formatNumber(failed, 0)} en échec</span> : null}
        </span>
        <span>{formatPercent(ratio)}</span>
      </p>
    </div>
  );
}

/** Small "← Retour" link above detail pages. */
export function BackLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="mb-3 inline-flex items-center gap-1.5 rounded text-[13px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <ArrowLeft className="size-3.5" aria-hidden />
      {children}
    </Link>
  );
}

/** Generic detail page skeleton. */
export function DetailSkeleton() {
  return (
    <div className="grid gap-4" aria-busy>
      <Skeleton className="h-9 w-72" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-72" />
    </div>
  );
}

/** Label / value pair for configuration summaries. */
export function MetaItem({ label, children, className }: { label: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("grid min-w-0 gap-1", className)}>
      <dt className="text-[11.5px] font-medium uppercase tracking-wide text-subtle-foreground">{label}</dt>
      <dd className="min-w-0 text-[13px] text-foreground">{children}</dd>
    </div>
  );
}

/** Table skeleton rows. */
export function TableSkeleton({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("grid gap-2 p-4", className)} aria-busy>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}
