"use client";

import * as React from "react";
import { Crown, Swords, TrendingDown } from "lucide-react";

import { TableSkeleton } from "@/components/benchmarks/common";
import { useUrlState } from "@/components/benchmarks/use-url-state";
import { CostDisplay, DurationDisplay } from "@/components/domain/metric-display";
import { ResultsAreaTabs } from "@/components/layout/area-tabs";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ARENA_PERIODS, useArena, type ArenaCategory, type ArenaModel } from "@/lib/api/arena";
import { useAgentOptions } from "@/lib/api/runs";
import { formatNumber, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

const ALL = "__all__";
const W = 560;
const H = 300;
const PAD = { left: 52, right: 20, top: 18, bottom: 40 };

interface Point {
  model: ArenaModel;
  x: number;
  y: number;
}

/** Cost per success on x (cheaper to the left), success rate on y (better up): the frontier is the upper-left edge. */
function Scatter({ category }: { category: ArenaCategory }) {
  const usable = category.models.filter((m) => m.usable && m.cost_per_success != null && m.pass_rate != null);
  if (usable.length === 0) return null;
  const costs = usable.map((m) => m.cost_per_success as number);
  const rates = usable.map((m) => m.pass_rate as number);
  const minCost = Math.min(...costs);
  const maxCost = Math.max(...costs);
  const minRate = Math.max(0, Math.min(...rates) - 0.05);
  const maxRate = Math.min(1, Math.max(...rates) + 0.05);
  const spanCost = maxCost - minCost || 1;
  const spanRate = maxRate - minRate || 1;
  const x = (c: number) => PAD.left + ((c - minCost) / spanCost) * (W - PAD.left - PAD.right);
  const y = (r: number) => H - PAD.bottom - ((r - minRate) / spanRate) * (H - PAD.top - PAD.bottom);
  const points: Point[] = usable.map((m) => ({ model: m, x: x(m.cost_per_success as number), y: y(m.pass_rate as number) }));
  const frontier = points.filter((p) => p.model.pareto).sort((a, b) => a.x - b.x);
  const line = frontier.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Taux de réussite selon le coût par réussite, par modèle" className="h-auto w-full">
      <line x1={PAD.left} y1={H - PAD.bottom} x2={W - PAD.right} y2={H - PAD.bottom} stroke="currentColor" opacity={0.25} />
      <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={H - PAD.bottom} stroke="currentColor" opacity={0.25} />
      <text x={W / 2} y={H - 8} textAnchor="middle" className="fill-current text-[11px]" opacity={0.65}>
        Coût par réussite → plus cher
      </text>
      <text x={14} y={H / 2} textAnchor="middle" transform={`rotate(-90 14 ${H / 2})`} className="fill-current text-[11px]" opacity={0.65}>
        Taux de réussite ↑
      </text>
      {[minRate, (minRate + maxRate) / 2, maxRate].map((r) => (
        <text key={r} x={PAD.left - 6} y={y(r) + 4} textAnchor="end" className="fill-current text-[10px]" opacity={0.6}>
          {formatPercent(r)}
        </text>
      ))}
      {line && frontier.length > 1 ? <path d={line} fill="none" stroke="var(--color-brand, #e11d48)" strokeWidth={2} strokeDasharray="6 4" opacity={0.7} /> : null}
      {points.map(({ model, x: px, y: py }) => (
        <g key={model.model}>
          {model.best_value ? <circle cx={px} cy={py} r={13} fill="none" stroke="var(--color-success, #16a34a)" strokeWidth={2} /> : null}
          <circle cx={px} cy={py} r={7} className={model.pareto ? "fill-brand" : "fill-muted-foreground"} opacity={model.pareto ? 1 : 0.55}>
            <title>{`${model.model} — ${formatPercent(model.pass_rate)} de réussite`}</title>
          </circle>
          <text
            x={px + (px > W - 100 ? 8 : px < PAD.left + 60 ? -8 : 0)}
            y={py - 14}
            textAnchor={px > W - 100 ? "end" : px < PAD.left + 60 ? "start" : "middle"}
            className="fill-current text-[11px] font-medium"
          >
            {model.model.length > 22 ? `${model.model.slice(0, 21)}…` : model.model}
          </text>
        </g>
      ))}
    </svg>
  );
}

function CategoryCard({ category }: { category: ArenaCategory }) {
  const models = [...category.models].sort((a, b) => (b.pass_rate ?? -1) - (a.pass_rate ?? -1));
  const usable = models.filter((m) => m.usable).length;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {category.category}
          <Badge tone="neutral">{`${models.length} modèle${models.length > 1 ? "s" : ""}`}</Badge>
        </CardTitle>
        <CardDescription>
          {usable < 2
            ? "Il faut au moins deux modèles avec assez de runs évalués et un coût connu pour les comparer."
            : "Plus un modèle est en haut à gauche, mieux c’est : il réussit plus souvent pour moins cher."}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {usable >= 1 ? <Scatter category={category} /> : null}
        {category.recommendations.length ? (
          <ul className="grid gap-2" aria-label="Recommandations">
            {category.recommendations.map((r) => (
              <li key={`${r.from_model}-${r.to_model}`} className="flex items-start gap-2 rounded-lg border border-border bg-success/5 p-3 text-sm">
                <TrendingDown className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
                <span>{r.message}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Modèle</TableHead>
              <TableHead className="text-right">Runs évalués</TableHead>
              <TableHead className="text-right">Réussite</TableHead>
              <TableHead className="text-right">Coût par réussite</TableHead>
              <TableHead className="text-right">Latence p95</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {models.map((m) => (
              <TableRow key={m.model} className={cn(!m.usable && "opacity-70")}>
                <TableCell className="font-medium">{m.model}</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(m.n_scored)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatPercent(m.pass_rate)}</TableCell>
                <TableCell className="text-right">
                  <CostDisplay value={m.cost_per_success} />
                </TableCell>
                <TableCell className="text-right">
                  <DurationDisplay ms={m.latency_p95 ?? undefined} />
                </TableCell>
                <TableCell className="text-right">
                  <span className="inline-flex flex-wrap justify-end gap-1">
                    {m.best_value ? (
                      <Badge tone="green" icon={<Crown />}>
                        Meilleur rapport
                      </Badge>
                    ) : null}
                    {m.pareto && !m.best_value ? <Badge tone="violet">Frontière</Badge> : null}
                    {!m.usable ? <Badge tone="neutral">Trop peu de runs</Badge> : null}
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

/**
 * « Analyser › Arène des modèles » : for each kind of work, the models side by side on success rate and cost per
 * success, the Pareto frontier (nothing beats these on both), the best value and where a cheaper model is as good.
 */
export function ArenaView() {
  const { get, set } = useUrlState();
  const daysParam = Number(get("days"));
  const days = (ARENA_PERIODS as readonly number[]).includes(daysParam) ? daysParam : 30;
  const agentId = get("agent_id") ?? undefined;
  const agents = useAgentOptions();
  const query = useArena({ days, agent_id: agentId });
  const categories = (query.data?.categories ?? []).filter((c) => c.models.length > 0);
  const compared = categories.filter((c) => c.models.filter((m) => m.usable).length >= 2).length;
  return (
    <div className="grid gap-6">
      <PageHeader
        icon={<Swords />}
        title="Arène des modèles"
        description="Quel modèle pour quel travail : sur les mêmes types de scénarios, la réussite, le coût par réussite et la latence de chaque modèle, avec la frontière où aucun autre ne fait mieux."
      />
      <ResultsAreaTabs />
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl
          aria-label="Période"
          value={String(days)}
          onValueChange={(v) => set({ days: v })}
          options={ARENA_PERIODS.map((d) => ({ value: String(d), label: `${d} jours` }))}
        />
        <SimpleSelect
          aria-label="Agent"
          value={agentId ?? ALL}
          onValueChange={(v) => set({ agent_id: v === ALL ? null : v })}
          options={[{ value: ALL, label: "Tous les agents" }, ...(agents.data?.items ?? []).map((a) => ({ value: a.id, label: a.name }))]}
        />
        {query.data ? (
          <span className="text-sm text-muted-foreground">
            {formatNumber(query.data.n_runs)} runs analysés · {compared} catégorie{compared > 1 ? "s" : ""} comparable{compared > 1 ? "s" : ""}
            {query.data.truncated ? " (échantillon limité aux runs les plus récents)" : ""}
          </span>
        ) : null}
      </div>
      {query.isLoading ? <TableSkeleton rows={5} /> : null}
      {query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : null}
      {query.data && categories.length === 0 ? (
        <EmptyState icon={<Swords />} title="Rien à comparer" description="Aucun run évalué sur cette période. Lancez la même comparaison avec plusieurs modèles pour les voir s’affronter ici." />
      ) : null}
      {categories.map((c) => (
        <CategoryCard key={c.category} category={c} />
      ))}
    </div>
  );
}
