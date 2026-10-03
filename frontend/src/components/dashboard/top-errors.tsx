"use client";

import Link from "next/link";
import { ArrowRight, Bug } from "lucide-react";

import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { dashboardScopeQuery, type Dashboard } from "@/lib/api/dashboard";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

const MAX_CAUSES = 5;
const SEVERITY_LABEL: Record<string, string> = {
  critical: "critique",
  high: "haute",
  medium: "moyenne",
  low: "faible",
};

/**
 * Level 2: the most frequent detected errors. One colour family only: red for critical/high,
 * orange for medium/low — the bar length carries the volume, the text carries the severity.
 */
export function TopErrors({
  data,
  days,
  className,
}: {
  data: Dashboard | undefined;
  days: number;
  className?: string;
}) {
  const causes = (data?.top_error_types ?? []).slice(0, MAX_CAUSES);
  const max = Math.max(1, ...causes.map((e) => e.count));
  return (
    <Card className={cn("h-full", className)}>
      <CardHeader className="flex-row items-start">
        <div className="grid gap-1">
          <CardTitle>Principales causes d&apos;erreur</CardTitle>
          <CardDescription>Erreurs détectées par les règles et les juges · {days} derniers jours</CardDescription>
        </div>
        <CardAction>
          <Link
            href="/errors"
            className="inline-flex items-center gap-1 rounded text-[13px] font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Voir toutes
            {data && data.error_types_total > MAX_CAUSES ? ` (${data.error_types_total})` : ""}
            <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        </CardAction>
      </CardHeader>
      <CardContent>
        {!data ? (
          <div className="grid gap-2">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : causes.length === 0 ? (
          <EmptyState
            size="sm"
            icon={<Bug />}
            title="Aucune erreur détectée"
            description="Aucune exécution évaluée n'a remonté d'erreur sur la période."
          />
        ) : (
          <ul className="grid gap-1">
            {causes.map((err) => {
              const severe = err.max_severity === "critical" || err.max_severity === "high";
              return (
                <li key={err.error_type}>
                  <Link
                    href={`/errors?${dashboardScopeQuery(data, { type: err.error_type })}`}
                    className="-mx-2 grid gap-1 rounded-md px-2 py-1.5 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <div className="flex items-baseline justify-between gap-3 text-[13px]">
                      <span className="min-w-0 truncate font-medium text-foreground">
                        {err.label}
                        <span className="ml-1.5 text-[11.5px] font-normal text-muted-foreground">
                          gravité max. {SEVERITY_LABEL[err.max_severity] ?? err.max_severity}
                        </span>
                      </span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">
                        <span className="font-semibold text-foreground">{formatNumber(err.count, 0)}</span>
                        <span className="hidden sm:inline"> · {formatNumber(err.runs_affected, 0)} exéc.</span>
                      </span>
                    </div>
                    <span className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                      <span
                        className={cn(
                          "block h-full rounded-full",
                          severe ? "bg-red-500/75 dark:bg-red-400/75" : "bg-amber-500/70 dark:bg-amber-400/70",
                        )}
                        style={{ width: `${(err.count / max) * 100}%` }}
                      />
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
