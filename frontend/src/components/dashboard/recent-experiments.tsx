"use client";

import Link from "next/link";
import { ArrowRight, CircleCheck, FlaskConical, Search, TriangleAlert } from "lucide-react";

import { DeltaIndicator } from "@/components/domain/delta-indicator";
import { RelativeTime } from "@/components/domain/relative-time";
import { ExecutionStatusBadge } from "@/components/domain/status-badge";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { Dashboard, DashboardRecentExperiment } from "@/lib/api/dashboard";
import { cn } from "@/lib/utils";

/**
 * Decision support, not a decision: the recommendation is computed from paired statistics and
 * regressions, the user decides. Labels say what was observed.
 */
const DECISION: Record<
  string,
  {
    label: string;
    className: string;
    icon: React.ComponentType<{ className?: string }>;
  }
> = {
  ship: {
    label: "Candidat recommandé",
    className: "bg-emerald-500/12 text-emerald-800 dark:text-emerald-300",
    icon: CircleCheck,
  },
  ship_with_caution: {
    label: "À examiner",
    className: "bg-amber-500/15 text-amber-800 dark:text-amber-300",
    icon: Search,
  },
  inconclusive: {
    label: "À examiner",
    className: "bg-amber-500/15 text-amber-800 dark:text-amber-300",
    icon: Search,
  },
  do_not_ship: {
    label: "Régression détectée",
    className: "bg-red-500/12 text-red-700 dark:text-red-300",
    icon: TriangleAlert,
  },
};

/** « ProductAgent v1.3 » → { system: "ProductAgent", version: "v1.3" } (labels come from the API). */
function splitLabel(label: string | null | undefined): {
  system: string | null;
  version: string;
} {
  if (!label) return { system: null, version: "—" };
  const i = label.lastIndexOf(" v");
  return i > 0 ? { system: label.slice(0, i), version: label.slice(i + 1) } : { system: null, version: label };
}

function ExperimentRow({ exp }: { exp: DashboardRecentExperiment }) {
  const base = splitLabel(exp.baseline_label);
  const cand = splitLabel(exp.candidate_label);
  const decision = exp.recommendation ? DECISION[exp.recommendation] : undefined;
  const sameSystem = base.system && base.system === cand.system;
  return (
    <li>
      <Link
        href={`/experiments/${exp.id}`}
        className="group -mx-2 grid gap-1 rounded-md px-2 py-2.5 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div className="flex min-w-0 items-center justify-between gap-3">
          <span className="min-w-0 truncate text-[13.5px] font-medium text-foreground">
            {sameSystem ? (
              <>
                {base.system} {base.version} <span aria-hidden>→</span>
                <span className="sr-only"> vers </span> {cand.version}
              </>
            ) : (
              <>
                {exp.baseline_label ?? "—"} <span aria-hidden>→</span>
                <span className="sr-only"> vers </span> {exp.candidate_label ?? "—"}
              </>
            )}
          </span>
          {decision ? (
            <span
              className={cn(
                "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-medium",
                decision.className,
              )}
            >
              <decision.icon className="size-3.5" aria-hidden />
              {decision.label}
            </span>
          ) : exp.status === "completed" ? null : (
            <span className="shrink-0 text-[12px] text-subtle-foreground">Analyse en cours</span>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
          <span className="flex flex-wrap items-center gap-x-2">
            {exp.status !== "completed" ? <ExecutionStatusBadge status={exp.status} /> : <span>Terminée</span>}
            <span aria-hidden>·</span>
            <RelativeTime date={exp.created_at} />
            {exp.critical_regressions > 0 ? (
              <>
                <span aria-hidden>·</span>
                <span className="text-red-700 dark:text-red-300">
                  {exp.critical_regressions}{" "}
                  {exp.critical_regressions > 1 ? "régressions critiques" : "régression critique"}
                </span>
              </>
            ) : null}
          </span>
          <span className="flex items-center gap-3">
            {typeof exp.composite_delta === "number" ? <DeltaIndicator value={exp.composite_delta} unit="pts" /> : null}
            <span className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary group-hover:underline">
              Voir l&apos;analyse <ArrowRight className="size-3.5" aria-hidden />
            </span>
          </span>
        </div>
      </Link>
    </li>
  );
}

/** Level 2: the latest baseline → candidate experiments (max 5) and what they found. */
export function RecentExperiments({ data, className }: { data: Dashboard | undefined; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader className="flex-row items-center">
        <CardTitle>Expériences récentes</CardTitle>
        <CardAction>
          <Link
            href="/experiments"
            className="inline-flex items-center gap-1 rounded text-[13px] font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Voir toutes <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        </CardAction>
      </CardHeader>
      <CardContent>
        {!data ? (
          <div className="grid gap-2">
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : data.recent_experiments.length === 0 ? (
          <EmptyState
            size="sm"
            icon={<FlaskConical />}
            title="Aucune expérience récente"
            description="Comparez une version candidate à sa version de référence pour mesurer le gain réel."
          />
        ) : (
          <ul className="grid divide-y divide-border">
            {data.recent_experiments.slice(0, 5).map((exp) => (
              <ExperimentRow key={exp.id} exp={exp} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
