"use client";

import * as React from "react";
import { Crown, ShieldAlert, TriangleAlert } from "lucide-react";

import { DimensionBadge } from "@/components/domain/dimension-badge";
import { DimensionRadar, type DimensionRadarSeries, type DimensionValues } from "@/components/domain/dimension-radar";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { CostDisplay, DurationDisplay, TokenCount } from "@/components/domain/metric-display";
import { ScoreBadge } from "@/components/domain/score-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CHART_COLORS } from "@/components/ui/chart";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimpleTooltip } from "@/components/ui/tooltip";
import type { AgentAggregate, BenchmarkSummary, RankingEntry } from "@/lib/api/benchmarks";
import { DIMENSIONS, type Dimension } from "@/lib/enums";
import { formatInterval, formatPercent, formatPValue, formatScore100, formatSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Mean with its 95 % CI on a 0–100 track (pure rendering of API values). */
export function CiBar({
  mean,
  low,
  high,
  className,
  width = 96,
}: {
  mean: number | null | undefined;
  low: number | null | undefined;
  high: number | null | undefined;
  className?: string;
  width?: number;
}) {
  if (typeof mean !== "number") return null;
  const x = (v: number) => (Math.max(0, Math.min(100, v)) / 100) * width;
  const hasCi = typeof low === "number" && typeof high === "number";
  return (
    <svg width={width} height={10} className={cn("overflow-visible", className)} aria-hidden>
      <line x1={0} x2={width} y1={5} y2={5} stroke="var(--chart-grid)" strokeWidth={2} strokeLinecap="round" />
      {hasCi ? (
        <line x1={x(low)} x2={x(high)} y1={5} y2={5} stroke="var(--chart-1)" strokeOpacity={0.45} strokeWidth={6} strokeLinecap="round" />
      ) : null}
      <circle cx={x(mean)} cy={5} r={3.5} fill="var(--chart-1)" stroke="var(--card)" strokeWidth={1.5} />
    </svg>
  );
}

function topErrors(byType: Record<string, number>, n = 3): Array<[string, number]> {
  return Object.entries(byType)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n);
}

export function agentColor(index: number): string {
  return CHART_COLORS[index % CHART_COLORS.length] ?? "var(--chart-1)";
}

/** Leaderboard per agent version (rank from the API). */
export function Leaderboard({ summary }: { summary: BenchmarkSummary }) {
  const ranking = new Map<string, RankingEntry>(summary.ranking.map((r) => [r.agent_version_id, r]));
  const agents = [...summary.agents].sort((a, b) => a.rank - b.rank);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Classement</CardTitle>
        <CardDescription>
          Composite moyen avec IC {formatPercent(summary.statistics.confidence)} ({summary.statistics.n_resamples.toLocaleString("fr-FR")}{" "}
          rééchantillonnages bootstrap). Le rang utilise le composite de groupe (robustesse incluse).
        </CardDescription>
      </CardHeader>
      <Table dense>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10">#</TableHead>
            <TableHead>Version</TableHead>
            <TableHead>Composite · IC 95 %</TableHead>
            <TableHead className="text-right">Réussite</TableHead>
            <TableHead className="text-right">Garde-fou</TableHead>
            <TableHead className="text-right">Robustesse</TableHead>
            <TableHead className="text-right">Coût moy. / total</TableHead>
            <TableHead className="text-right">Latence moy. / p95</TableHead>
            <TableHead className="text-right">Tokens moy.</TableHead>
            <TableHead>Principales erreurs</TableHead>
            <TableHead className="text-right">Écart au 1er</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {agents.map((a, i) => {
            const r = ranking.get(a.agent_version_id);
            return (
              <TableRow key={a.agent_version_id}>
                <TableCell className="tabular-nums">
                  {a.rank === 1 ? (
                    <span className="inline-flex items-center gap-1 font-semibold text-amber-600 dark:text-amber-400">
                      <Crown className="size-3.5" aria-label="Premier" />1
                    </span>
                  ) : (
                    <span className="text-muted-foreground">{a.rank}</span>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <span className="size-2.5 shrink-0 rounded-[3px]" style={{ backgroundColor: agentColor(i) }} aria-hidden />
                    <div className="grid">
                      <span className="font-medium">{a.agent_label}</span>
                      <span className="text-xs text-muted-foreground">
                        {a.model ?? "modèle non déclaré"} · {a.n_scored}/{a.n_runs} runs notés
                        {a.n_failed ? ` · ${a.n_failed} en échec` : ""}
                      </span>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <ScoreBadge value={a.composite.mean} />
                    <div className="grid gap-0.5">
                      <CiBar mean={a.composite.mean} low={a.composite.ci_low} high={a.composite.ci_high} />
                      <span className="text-[11px] tabular-nums text-muted-foreground">
                        {formatInterval(a.composite.ci_low, a.composite.ci_high)}
                      </span>
                    </div>
                  </div>
                  {typeof a.group_composite === "number" ? (
                    <span className="text-[11px] text-subtle-foreground">Groupe : {formatScore100(a.group_composite)}</span>
                  ) : null}
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatPercent(a.pass_rate)}</TableCell>
                <TableCell className="text-right tabular-nums">
                  <span className={cn((a.gate_failure_rate ?? 0) > 0 && "inline-flex items-center gap-1 text-red-700 dark:text-red-400")}>
                    {(a.gate_failure_rate ?? 0) > 0 ? <ShieldAlert className="size-3.5" aria-hidden /> : null}
                    {formatPercent(a.gate_failure_rate)}
                  </span>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  <SimpleTooltip content={`${a.robustness.n_families} famille(s) de variantes`}>
                    <span tabIndex={0}>{a.robustness.value === null || a.robustness.value === undefined ? "—" : formatPercent(a.robustness.value, 1)}</span>
                  </SimpleTooltip>
                </TableCell>
                <TableCell className="text-right">
                  <CostDisplay value={a.cost.mean} />
                  <span className="block text-[11px] text-muted-foreground">
                    <CostDisplay value={a.cost.total} muted />
                  </span>
                </TableCell>
                <TableCell className="text-right">
                  <DurationDisplay ms={a.latency.mean} />
                  <span className="block text-[11px] text-muted-foreground">
                    p95 <DurationDisplay ms={a.latency.p95} muted />
                  </span>
                </TableCell>
                <TableCell className="text-right">
                  <TokenCount total={a.tokens.mean} unit={false} />
                </TableCell>
                <TableCell>
                  <div className="flex max-w-60 flex-wrap gap-1">
                    {topErrors(a.errors_by_type).map(([code, n]) => (
                      <ErrorTypeBadge key={code} code={code} count={n} />
                    ))}
                    {Object.keys(a.errors_by_type).length === 0 ? <span className="text-xs text-subtle-foreground">Aucune</span> : null}
                  </div>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {a.rank === 1 ? (
                    <span className="text-xs text-muted-foreground">Leader</span>
                  ) : r ? (
                    <SimpleTooltip
                      content={
                        a.vs_leader
                          ? `${a.vs_leader.n_pairs} paires · IC ${formatInterval(a.vs_leader.ci_low, a.vs_leader.ci_high)} · ${formatPValue(a.vs_leader.p_value)}`
                          : undefined
                      }
                    >
                      <span tabIndex={0} className="grid justify-items-end">
                        <span>{formatSigned(r.delta_to_leader, { unit: "pts" })}</span>
                        <span className="text-[11px] text-muted-foreground">
                          {r.significant_gap === true ? "significatif" : r.significant_gap === false ? "non significatif" : "—"}
                        </span>
                      </span>
                    </SimpleTooltip>
                  ) : (
                    "—"
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Card>
  );
}

function dimensionValues(a: AgentAggregate): DimensionValues {
  const out: DimensionValues = {};
  for (const d of DIMENSIONS) {
    const v = a.dimensions[d];
    if (typeof v === "number") out[d as Dimension] = v;
  }
  return out;
}

/** Dimension radar comparing every agent version + best version per dimension. */
export function AgentsRadarCard({ summary }: { summary: BenchmarkSummary }) {
  const agents = [...summary.agents].sort((a, b) => a.rank - b.rank);
  const [first, ...rest] = agents;
  if (!first) return null;
  const extra: DimensionRadarSeries[] = rest.map((a, i) => ({ label: a.agent_label, values: dimensionValues(a), color: agentColor(i + 1) }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Dimensions par version</CardTitle>
        <CardDescription>Scores moyens normalisés (0–100) ; robustesse mesurée sur les variantes et répétitions.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <DimensionRadar values={dimensionValues(first)} label={first.agent_label} extraSeries={extra} height={300} />
        {summary.best_by_dimension.length ? (
          <div className="grid gap-1.5">
            <p className="text-[11.5px] font-medium uppercase tracking-wide text-subtle-foreground">Meilleure version par dimension</p>
            <ul className="grid gap-1 sm:grid-cols-2">
              {summary.best_by_dimension.map((b) => (
                <li key={b.dimension} className="flex items-center justify-between gap-2 text-[13px]">
                  <DimensionBadge dimension={b.dimension} />
                  <span className="truncate text-muted-foreground">
                    {b.agent_label} · <span className="tabular-nums text-foreground">{formatScore100(b.value * 100)}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** Generalisation gap (public vs private + fresh), per agent version. */
export function GeneralisationCard({ summary }: { summary: BenchmarkSummary }) {
  const agents = [...summary.agents].sort((a, b) => a.rank - b.rank);
  const alerts = agents.filter((a) => a.generalisation.alert);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Écart de généralisation</CardTitle>
        <CardDescription>
          Composite sur les scénarios publics vs privés + fresh : un écart positif important signale un sur-apprentissage
          des scénarios publics.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {alerts.length ? (
          <Alert tone="amber" icon={<TriangleAlert aria-hidden />} title="Sur-apprentissage suspecté">
            {alerts.map((a) => a.agent_label).join(", ")} : nettement meilleur(s) sur les scénarios publics que sur les
            scénarios privés et récents.
          </Alert>
        ) : (
          <Alert tone="green" title="Pas d'écart de généralisation signalé">
            Les scores sur les scénarios privés et fresh sont cohérents avec les scénarios publics.
          </Alert>
        )}
        <Table dense>
          <TableHeader>
            <TableRow>
              <TableHead>Version</TableHead>
              <TableHead className="text-right">Publics</TableHead>
              <TableHead className="text-right">Privés</TableHead>
              <TableHead className="text-right">Fresh</TableHead>
              <TableHead className="text-right">Privés + fresh</TableHead>
              <TableHead className="text-right">Écart</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {agents.map((a) => {
              const g = a.generalisation;
              return (
                <TableRow key={a.agent_version_id}>
                  <TableCell className="font-medium">
                    {a.agent_label}
                    {g.alert ? (
                      <Badge tone="amber" className="ml-2">
                        Alerte
                      </Badge>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatScore100(g.public_mean)} <span className="text-[11px] text-muted-foreground">({g.n_public})</span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatScore100(g.private_mean)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatScore100(g.fresh_mean)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatScore100(g.hidden_mean)} <span className="text-[11px] text-muted-foreground">({g.n_hidden})</span>
                  </TableCell>
                  <TableCell className={cn("text-right font-medium tabular-nums", g.alert && "text-amber-700 dark:text-amber-400")}>
                    {formatSigned(g.gap, { unit: "pts" })}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
