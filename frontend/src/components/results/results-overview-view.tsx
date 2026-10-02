"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, BarChart3, Inbox } from "lucide-react";

import { TableSkeleton } from "@/components/benchmarks/common";
import { useUrlState } from "@/components/benchmarks/use-url-state";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { CostDisplay, DurationDisplay } from "@/components/domain/metric-display";
import { ScoreBadge } from "@/components/domain/score-badge";
import { SeverityBadge } from "@/components/domain/severity-badge";
import { ResultsAreaTabs } from "@/components/layout/area-tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RESULTS_PERIODS, useResultsOverview, type ResultsAgentRow } from "@/lib/api/results";
import { useAgentOptions } from "@/lib/api/runs";
import { isEnumValue, ERROR_SEVERITIES } from "@/lib/enums";
import { formatNumber, formatPercent } from "@/lib/format";

const ALL = "__all__";

function topError(row: ResultsAgentRow): [string, number] | null {
  const entries = Object.entries(row.errors_by_type ?? {}).sort((a, b) => b[1] - a[1]);
  return entries[0] ?? null;
}

/**
 * « Analyser › Résultats » : how each agent version performed on the evaluated runs of the period
 * (ad hoc, comparisons and experiments alike), then where it fails (« Erreurs détectées » tab).
 */
export function ResultsOverviewView() {
  const router = useRouter();
  const { get, set } = useUrlState();
  const daysParam = Number(get("days"));
  const days = (RESULTS_PERIODS as readonly number[]).includes(daysParam) ? daysParam : 30;
  const agentId = get("agent_id") ?? undefined;
  const agents = useAgentOptions();
  const query = useResultsOverview({ days, agent_id: agentId });
  const rows = query.data?.agents ?? [];
  const errors = query.data?.errors ?? [];

  return (
    <>
      <PageHeader
        eyebrow="Analyser"
        title="Résultats"
        icon={<BarChart3 />}
        description="Comment chaque version d'agent se comporte sur les exécutions évaluées de la période : score, réussite, garde-fous, erreurs, coût et latence."
        actions={
          <SegmentedControl
            aria-label="Période"
            value={String(days)}
            onValueChange={(v) => set({ days: v === "30" ? null : v })}
            options={RESULTS_PERIODS.map((d) => ({ value: String(d), label: `${d} j` }))}
          />
        }
      >
        <ResultsAreaTabs />
      </PageHeader>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SimpleSelect
          aria-label="Agent"
          size="sm"
          className="w-60"
          value={agentId ?? ALL}
          onValueChange={(v) => set({ agent_id: v === ALL ? null : v })}
          options={[
            { value: ALL, label: "Tous les agents" },
            ...(agents.data?.items ?? []).map((a) => ({ value: a.id, label: a.name })),
          ]}
        />
        {query.data ? (
          <p className="text-[13px] text-muted-foreground">
            {formatNumber(query.data.n_runs, 0)} exécution{query.data.n_runs > 1 ? "s" : ""} évaluée
            {query.data.n_runs > 1 ? "s" : ""} sur {days} jours
            {query.data.truncated ? " (les plus récentes)" : ""}
          </p>
        ) : null}
      </div>

      {query.isError && !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_340px]">
          <Card>
            <CardHeader>
              <CardTitle>Par version d&apos;agent</CardTitle>
              <CardDescription>
                Score composite moyen (IC 95 %), taux de réussite et part des exécutions avec au moins une erreur détectée.
              </CardDescription>
            </CardHeader>
            {query.isPending ? (
              <TableSkeleton rows={4} />
            ) : rows.length === 0 ? (
              <CardContent>
                <EmptyState
                  icon={<Inbox />}
                  title="Aucune exécution évaluée sur la période"
                  description="Lancez des exécutions ou une comparaison pour obtenir des résultats."
                  action={
                    <Button asChild size="sm" variant="secondary">
                      <Link href="/runs">Voir les exécutions</Link>
                    </Button>
                  }
                />
              </CardContent>
            ) : (
              <Table dense>
                <TableHeader>
                  <TableRow>
                    <TableHead>Version</TableHead>
                    <TableHead className="text-right">Exécutions</TableHead>
                    <TableHead>Score</TableHead>
                    <TableHead className="text-right">Réussite</TableHead>
                    <TableHead className="hidden text-right md:table-cell">Avec erreurs</TableHead>
                    <TableHead className="hidden lg:table-cell">Erreur principale</TableHead>
                    <TableHead className="hidden text-right md:table-cell">Coût moyen</TableHead>
                    <TableHead className="hidden text-right lg:table-cell">Latence p95</TableHead>
                    <TableHead className="w-8">
                      <span className="sr-only">Ouvrir</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => {
                    const href = `/runs?agent_version_id=${row.agent_version_id}&agent_id=${row.agent_id}`;
                    const top = topError(row);
                    return (
                      <TableRow
                        key={row.agent_version_id}
                        className="cursor-pointer"
                        onClick={() => router.push(href)}
                      >
                        <TableCell>
                          <Link href={href} className="whitespace-nowrap font-medium text-foreground hover:underline" onClick={(e) => e.stopPropagation()}>
                            {row.agent_label}
                          </Link>
                          {row.model ? <div className="font-mono text-[11px] text-muted-foreground">{row.model}</div> : null}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatNumber(row.n_runs, 0)}
                          {row.n_failed ? (
                            <Badge tone="red" size="sm" className="ml-1.5">
                              {row.n_failed} en échec
                            </Badge>
                          ) : null}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <ScoreBadge value={row.composite_mean} />
                            {typeof row.composite_ci_low === "number" && typeof row.composite_ci_high === "number" ? (
                              <span className="hidden whitespace-nowrap text-[11px] tabular-nums text-muted-foreground xl:inline">
                                [{formatNumber(row.composite_ci_low, 1)} ; {formatNumber(row.composite_ci_high, 1)}]
                              </span>
                            ) : null}
                          </div>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{formatPercent(row.pass_rate)}</TableCell>
                        <TableCell className="hidden text-right tabular-nums md:table-cell">{formatPercent(row.error_rate)}</TableCell>
                        <TableCell className="hidden lg:table-cell">
                          {top ? <ErrorTypeBadge code={top[0]} count={top[1]} /> : <span className="text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell className="hidden text-right md:table-cell">
                          <CostDisplay value={row.cost_mean} />
                        </TableCell>
                        <TableCell className="hidden text-right lg:table-cell">
                          <DurationDisplay ms={row.latency_p95} />
                        </TableCell>
                        <TableCell>
                          <ArrowRight className="size-4 text-subtle-foreground" aria-hidden />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Erreurs les plus fréquentes</CardTitle>
              <CardDescription>Occurrences sur les mêmes exécutions. Ouvrez un type pour voir les cas et leurs preuves.</CardDescription>
            </CardHeader>
            <CardContent>
              {query.isPending ? (
                <TableSkeleton rows={4} className="p-0" />
              ) : errors.length === 0 ? (
                <p className="text-sm text-muted-foreground">Aucune erreur détectée sur la période.</p>
              ) : (
                <ul className="grid gap-1 sm:grid-cols-2 2xl:grid-cols-1">
                  {errors.map((e) => (
                    <li key={e.error_type}>
                      <Link
                        href={`/errors?type=${encodeURIComponent(e.error_type)}`}
                        className="flex items-center gap-2 rounded-md px-2 py-1.5 transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <ErrorTypeBadge code={e.error_type} />
                        {isEnumValue(ERROR_SEVERITIES, e.max_severity) ? <SeverityBadge severity={e.max_severity} /> : null}
                        <span
                          className="ml-auto whitespace-nowrap text-[12.5px] tabular-nums text-muted-foreground"
                          title={`${e.count} occurrence(s) sur ${e.runs_affected} exécution(s)`}
                        >
                          {formatNumber(e.count, 0)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
              <Button asChild variant="ghost" size="sm" className="mt-3">
                <Link href="/errors">
                  Toutes les erreurs détectées <ArrowRight aria-hidden />
                </Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
