"use client";

import * as React from "react";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  Bot,
  Bug,
  CircleCheck,
  Coins,
  FlaskConical,
  Gauge,
  Inbox,
  Layers,
  LayoutDashboard,
  ListOrdered,
  Play,
  ScrollText,
  Timer,
  TriangleAlert,
} from "lucide-react";

import { RoleButton } from "@/components/agents/kit/role-button";
import { useUrlState } from "@/components/agents/kit/use-url-state";
import { DeltaIndicator } from "@/components/domain/delta-indicator";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { KpiCard, KpiCardSkeleton } from "@/components/domain/kpi-card";
import { RelativeTime } from "@/components/domain/relative-time";
import { ExecutionStatusBadge, RunStatusBadge } from "@/components/domain/status-badge";
import { RecommendationBadge } from "@/components/domain/verdict-badge";
import { CHART_COLORS } from "@/components/ui/chart";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Progress } from "@/components/ui/progress";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { DASHBOARD_PERIODS, useDashboard, type Dashboard, type DashboardPeriod } from "@/lib/api/dashboard";
import { getMeta, JOB_QUEUE_META, RUN_STATUSES, type JobQueue } from "@/lib/enums";
import { formatCost, formatMs, formatNumber, formatPercent, formatScore100, plural } from "@/lib/format";
import { cn } from "@/lib/utils";

import { TrendChart } from "./trend-chart";

function parsePeriod(raw: string): DashboardPeriod {
  const n = Number(raw);
  return (DASHBOARD_PERIODS as readonly number[]).includes(n) ? (n as DashboardPeriod) : 30;
}

/** Tableau de bord : `GET /dashboard?days=` (all figures are computed by the API). */
export function DashboardView() {
  const url = useUrlState();
  const days = parsePeriod(url.get("days"));
  const query = useDashboard(days);
  const data = query.data;

  return (
    <>
      <PageHeader
        eyebrow="Pilotage"
        title="Tableau de bord"
        icon={<LayoutDashboard />}
        description="Vue d'ensemble des évaluations : scores, coûts, latences, erreurs et activité récente."
        meta={query.isFetching && !query.isPending ? <Spinner label="Actualisation…" /> : null}
        actions={
          <SegmentedControl
            aria-label="Période"
            value={String(days)}
            onValueChange={(v) => url.set({ days: v === "30" ? null : v })}
            options={DASHBOARD_PERIODS.map((d) => ({ value: String(d), label: `${d} j` }))}
          />
        }
      />

      {query.isError && !data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div className={cn("grid gap-4 transition-opacity", query.isPlaceholderData && "opacity-70")}>
          <QuickActions />
          <KpiGrid data={data} days={days} />
          <TrendsSection data={data} />
          <div className="grid gap-4 xl:grid-cols-3">
            <RecentExperiments data={data} className="xl:col-span-2" />
            <TopErrors data={data} days={days} />
            <RecentExecutions data={data} className="xl:col-span-2" />
            <WorkerActivity data={data} />
          </div>
        </div>
      )}
    </>
  );
}

function QuickActions() {
  return (
    <section aria-label="Actions rapides" className="flex flex-wrap gap-2">
      <RoleButton minRole="editor" href="/runs?new=1" leftIcon={<Play aria-hidden />} size="sm">
        Nouveau run
      </RoleButton>
      <RoleButton minRole="editor" href="/benchmarks?new=1" variant="secondary" leftIcon={<Layers aria-hidden />} size="sm">
        Nouveau benchmark
      </RoleButton>
      <RoleButton
        minRole="editor"
        href="/experiments?new=1"
        variant="secondary"
        leftIcon={<FlaskConical aria-hidden />}
        size="sm"
      >
        Nouvelle expérience
      </RoleButton>
    </section>
  );
}

function trend(data: Dashboard | undefined, key: "average_composite" | "average_cost" | "average_latency_ms" | "error_rate" | "pass_rate" | "runs") {
  return data?.trends.map((t) => t[key] ?? null);
}

function KpiGrid({ data, days }: { data: Dashboard | undefined; days: number }) {
  if (!data) {
    return (
      <section aria-label="Indicateurs clés" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 8 }, (_, i) => (
          <KpiCardSkeleton key={i} />
        ))}
      </section>
    );
  }
  const { counts, kpis } = data;
  return (
    <section aria-label="Indicateurs clés" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <KpiCard
        label="Agents"
        icon={<Bot />}
        tone="orange"
        value={formatNumber(counts.agents, 0)}
        hint={plural(counts.agent_versions, "version")}
        href="/agents"
      />
      <KpiCard label="Scénarios" icon={<ScrollText />} tone="blue" value={formatNumber(counts.scenarios, 0)} href="/scenarios" />
      <KpiCard
        label={`Runs (${days} j)`}
        icon={<Play />}
        tone="violet"
        value={formatNumber(counts.runs, 0)}
        hint={`${plural(kpis.evaluated_runs, "run évalué", "runs évalués")}`}
        trend={trend(data, "runs")}
        href="/runs"
      />
      <KpiCard
        label="Score composite moyen"
        icon={<Gauge />}
        tone="orange"
        value={formatScore100(kpis.average_composite)}
        unit={kpis.average_composite !== null && kpis.average_composite !== undefined ? "/ 100" : undefined}
        trend={trend(data, "average_composite")}
        trendDomain={[0, 100]}
      />
      <KpiCard
        label="Coût moyen par run"
        icon={<Coins />}
        tone="amber"
        value={formatCost(kpis.average_cost)}
        hint={kpis.total_cost !== null && kpis.total_cost !== undefined ? `Total : ${formatCost(kpis.total_cost)}` : undefined}
        trend={trend(data, "average_cost")}
      />
      <KpiCard
        label="Latence moyenne"
        icon={<Timer />}
        tone="sky"
        value={formatMs(kpis.average_latency_ms)}
        trend={trend(data, "average_latency_ms")}
      />
      <KpiCard
        label="Taux d'erreur"
        icon={<Bug />}
        tone="red"
        value={formatPercent(kpis.error_rate)}
        hint={`Runs en échec : ${formatPercent(kpis.failure_rate)}`}
        trend={trend(data, "error_rate")}
        trendDomain={[0, 1]}
        href="/errors"
      />
      <KpiCard
        label="Taux de réussite"
        icon={<CircleCheck />}
        tone="green"
        value={formatPercent(kpis.pass_rate)}
        hint="Runs au-dessus du seuil, sans garde-fou en échec"
        trend={trend(data, "pass_rate")}
        trendDomain={[0, 1]}
      />
    </section>
  );
}

function TrendsSection({ data }: { data: Dashboard | undefined }) {
  const charts = [
    {
      key: "average_composite" as const,
      title: "Score composite moyen",
      description: "Moyenne quotidienne (0–100)",
      format: (v: number) => formatScore100(v),
      tick: (v: number) => formatNumber(v, 0),
      domain: [0, 100] as [number, number],
      color: CHART_COLORS[0],
    },
    {
      key: "average_cost" as const,
      title: "Coût moyen par run",
      description: "Coût estimé moyen par jour",
      format: (v: number) => formatCost(v),
      tick: undefined,
      domain: [0, "auto"] as [number, "auto"],
      color: CHART_COLORS[1],
    },
    {
      key: "average_latency_ms" as const,
      title: "Latence moyenne",
      description: "Temps de bout en bout moyen par jour",
      format: (v: number) => formatMs(v),
      tick: undefined,
      domain: [0, "auto"] as [number, "auto"],
      color: CHART_COLORS[2],
    },
    {
      key: "error_rate" as const,
      title: "Taux d'erreur",
      description: "Part des runs évalués avec au moins une erreur",
      format: (v: number) => formatPercent(v),
      tick: undefined,
      domain: [0, 1] as [number, number],
      color: CHART_COLORS[3],
    },
  ];
  return (
    <section aria-label="Tendances" className="grid gap-4 lg:grid-cols-2">
      {charts.map((c) => (
        <Card key={c.key}>
          <CardHeader>
            <CardTitle>{c.title}</CardTitle>
            <CardDescription>{c.description}</CardDescription>
          </CardHeader>
          <CardContent>
            {data ? (
              <TrendChart
                data={data.trends}
                dataKey={c.key}
                name={c.title}
                color={c.color}
                valueFormatter={c.format}
                tickFormatter={c.tick}
                domain={c.domain}
              />
            ) : (
              <Skeleton className="h-[180px] w-full" />
            )}
          </CardContent>
        </Card>
      ))}
    </section>
  );
}

function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="grid gap-2">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-11 w-full" />
      ))}
    </div>
  );
}

function SeeAll({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1 rounded text-[13px] font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {label}
      <ArrowRight className="size-3.5" aria-hidden />
    </Link>
  );
}

function RecentExperiments({ data, className }: { data: Dashboard | undefined; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader className="flex-row items-start">
        <div className="grid gap-1">
          <CardTitle>Expériences récentes</CardTitle>
          <CardDescription>Baseline vs candidate : recommandation et variation du composite</CardDescription>
        </div>
        <CardAction>
          <SeeAll href="/experiments" label="Toutes" />
        </CardAction>
      </CardHeader>
      <CardContent>
        {!data ? (
          <ListSkeleton />
        ) : data.recent_experiments.length === 0 ? (
          <EmptyState
            size="sm"
            icon={<FlaskConical />}
            title="Aucune expérience récente"
            description="Comparez une version candidate à sa baseline pour obtenir un verdict."
          />
        ) : (
          <ul className="grid divide-y divide-border">
            {data.recent_experiments.map((exp) => {
              const progress = exp.total_runs ? ((exp.completed_runs + exp.failed_runs) / exp.total_runs) * 100 : 0;
              return (
                <li key={exp.id}>
                  <Link
                    href={`/experiments/${exp.id}`}
                    className="-mx-2 grid gap-2 rounded-md px-2 py-2.5 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                  >
                    <div className="grid min-w-0 gap-1">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="truncate text-[13px] font-medium text-foreground">{exp.name}</span>
                        <ExecutionStatusBadge status={exp.status} />
                      </div>
                      <p className="truncate text-xs text-muted-foreground">
                        {exp.baseline_label ?? "—"} <span aria-hidden>→</span>
                        <span className="sr-only">vers</span> {exp.candidate_label ?? "—"} ·{" "}
                        <RelativeTime date={exp.created_at} />
                      </p>
                      {exp.status !== "completed" && exp.total_runs > 0 ? (
                        <Progress value={progress} size="xs" className="max-w-48" aria-label="Progression" />
                      ) : null}
                    </div>
                    <div className="flex items-center gap-3">
                      {exp.composite_delta !== null && exp.composite_delta !== undefined ? (
                        <DeltaIndicator value={exp.composite_delta} unit="pts" />
                      ) : null}
                      {exp.recommendation ? (
                        <RecommendationBadge recommendation={exp.recommendation} size="sm" noTooltip />
                      ) : (
                        <span className="text-xs text-subtle-foreground">Recommandation en attente</span>
                      )}
                    </div>
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

function TopErrors({ data, days }: { data: Dashboard | undefined; days: number }) {
  const max = Math.max(1, ...(data?.top_error_types.map((e) => e.count) ?? [1]));
  return (
    <Card>
      <CardHeader className="flex-row items-start">
        <div className="grid gap-1">
          <CardTitle>Erreurs les plus fréquentes</CardTitle>
          <CardDescription>Sur les {days} derniers jours</CardDescription>
        </div>
        <CardAction>
          <SeeAll href="/errors" label="Explorer" />
        </CardAction>
      </CardHeader>
      <CardContent>
        {!data ? (
          <ListSkeleton rows={5} />
        ) : data.top_error_types.length === 0 ? (
          <EmptyState size="sm" icon={<Bug />} title="Aucune erreur détectée" description="Aucun run évalué n'a remonté d'erreur sur la période." />
        ) : (
          <ul className="grid gap-3">
            {data.top_error_types.map((err) => (
              <li key={err.error_type}>
                <Link
                  href={`/errors?error_type=${encodeURIComponent(err.error_type)}`}
                  className="-mx-2 grid gap-1.5 rounded-md px-2 py-1.5 hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <div className="flex items-center justify-between gap-2">
                    <ErrorTypeBadge code={err.error_type} label={err.label} />
                    <span className="text-xs tabular-nums text-muted-foreground">
                      <span className="font-semibold text-foreground">{formatNumber(err.count, 0)}</span> ·{" "}
                      {plural(err.runs_affected, "run")}
                    </span>
                  </div>
                  <span className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                    <span className="block h-full rounded-full bg-red-500/70 dark:bg-red-400/70" style={{ width: `${(err.count / max) * 100}%` }} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function RecentExecutions({ data, className }: { data: Dashboard | undefined; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader className="flex-row items-start">
        <div className="grid gap-1">
          <CardTitle>Exécutions de benchmark récentes</CardTitle>
          <CardDescription>Progression et version en tête</CardDescription>
        </div>
        <CardAction>
          <SeeAll href="/benchmarks" label="Tous" />
        </CardAction>
      </CardHeader>
      <CardContent>
        {!data ? (
          <ListSkeleton />
        ) : data.recent_benchmark_executions.length === 0 ? (
          <EmptyState
            size="sm"
            icon={<Layers />}
            title="Aucune exécution récente"
            description="Lancez un benchmark pour comparer plusieurs versions d'agents sur une matrice de scénarios."
          />
        ) : (
          <ul className="grid divide-y divide-border">
            {data.recent_benchmark_executions.map((ex) => {
              const done = ex.completed_runs + ex.failed_runs;
              return (
                <li key={ex.id}>
                  <Link
                    href={`/benchmarks/${ex.benchmark_id}?execution=${ex.id}`}
                    className="-mx-2 grid gap-2 rounded-md px-2 py-2.5 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                  >
                    <div className="grid min-w-0 gap-1">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="truncate text-[13px] font-medium text-foreground">
                          {ex.benchmark_name} <span className="text-muted-foreground">#{ex.number}</span>
                        </span>
                        <ExecutionStatusBadge status={ex.status} />
                      </div>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Progress
                          value={ex.total_runs ? (done / ex.total_runs) * 100 : 0}
                          size="xs"
                          tone={ex.failed_runs ? "amber" : "orange"}
                          className="w-28"
                          aria-label="Progression"
                        />
                        <span className="tabular-nums">
                          {formatNumber(done, 0)} / {formatNumber(ex.total_runs, 0)} runs
                          {ex.failed_runs ? ` · ${plural(ex.failed_runs, "échec")}` : ""}
                        </span>
                        <span aria-hidden>·</span>
                        <RelativeTime date={ex.created_at} />
                      </div>
                    </div>
                    <div className="text-right text-xs">
                      {ex.leader_label ? (
                        <>
                          <p className="text-muted-foreground">En tête</p>
                          <p className="font-medium text-foreground">
                            {ex.leader_label}
                            {ex.leader_score !== null && ex.leader_score !== undefined ? (
                              <span className="ml-1.5 tabular-nums text-muted-foreground">{formatScore100(ex.leader_score)}</span>
                            ) : null}
                          </p>
                        </>
                      ) : null}
                    </div>
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

/** Queue depth + run statuses over the period. */
function WorkerActivity({ data }: { data: Dashboard | undefined }) {
  const queues = Object.entries(data?.queue_depth ?? {});
  const totalQueued = queues.reduce((s, [, n]) => s + n, 0);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="size-4 text-muted-foreground" aria-hidden />
          Activité des workers
        </CardTitle>
        <CardDescription>Jobs en file et statut des runs de la période</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {!data ? (
          <ListSkeleton rows={3} />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2">
              {queues.length === 0 ? (
                <p className="col-span-2 text-xs text-muted-foreground">File de jobs vide.</p>
              ) : (
                queues.map(([queue, depth]) => (
                  <div key={queue} className="rounded-lg border border-border bg-muted/30 px-3 py-2">
                    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <ListOrdered className="size-3.5" aria-hidden />
                      {getMeta(JOB_QUEUE_META, queue as JobQueue).label}
                    </p>
                    <p className="text-xl font-semibold tabular-nums text-foreground">{formatNumber(depth, 0)}</p>
                    <p className="text-[11px] text-subtle-foreground">{depth ? "jobs en attente" : "aucun job en attente"}</p>
                  </div>
                ))
              )}
            </div>
            {totalQueued > 50 ? (
              <p className="flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-300">
                <TriangleAlert className="size-3.5" aria-hidden /> File chargée : les résultats peuvent arriver avec du retard.
              </p>
            ) : null}
            <ul className="grid gap-1.5" aria-label="Runs par statut">
              {RUN_STATUSES.map((status) => {
                const n = data.runs_by_status[status] ?? 0;
                return (
                  <li key={status} className="flex items-center justify-between gap-2 text-[13px]">
                    <Link
                      href={`/runs?status=${status}`}
                      className="rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <RunStatusBadge status={status} />
                    </Link>
                    <span className={cn("tabular-nums", n ? "font-medium text-foreground" : "text-subtle-foreground")}>
                      {formatNumber(n, 0)}
                    </span>
                  </li>
                );
              })}
            </ul>
            {data.counts.runs === 0 ? (
              <EmptyState
                size="sm"
                variant="plain"
                icon={<Inbox />}
                title="Aucun run sur la période"
                description="Lancez un run ponctuel, un benchmark ou une expérience pour alimenter le tableau de bord."
              />
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
