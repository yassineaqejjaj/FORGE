"use client";

import * as React from "react";
import Link from "next/link";
import { Bug, ExternalLink, Inbox, OctagonAlert, Play } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Tooltip, XAxis, YAxis } from "recharts";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { EvaluatorKindBadge, RunOriginBadge } from "@/components/domain/enum-badge";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { KpiCard } from "@/components/domain/kpi-card";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { RelativeTime } from "@/components/domain/relative-time";
import { SeverityBadge } from "@/components/domain/severity-badge";
import { DateFilter, FilterBar, FilterSelect, MultiFilter, SearchFilter } from "@/components/runs/filter-controls";
import { dateInputToIso, useSearchState } from "@/components/runs/use-search-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CHART_COLORS, ChartContainer, chartAxisProps, chartCursor } from "@/components/ui/chart";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ResultsAreaTabs } from "@/components/layout/area-tabs";
import { useErrorsExplorer, useErrorTypes, type ErrorAggregations, type ErrorItem, type ErrorsParams } from "@/lib/api/errors";
import { useAgentOptions, useAgentVersionOptions, useScenarioOptions } from "@/lib/api/runs";
import { DEFAULT_PAGE_SIZE } from "@/lib/api/types";
import { ERROR_SEVERITIES, ERROR_SEVERITY_META, enumOptions, SCENARIO_CATEGORIES, type ErrorSeverity } from "@/lib/enums";
import { formatNumber, formatPercent, truncate } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

const FILTER_KEYS = [
  "type",
  "severity",
  "agent_id",
  "agent_version_id",
  "scenario_id",
  "category",
  "benchmark_execution_id",
  "experiment_id",
  "run_id",
  "from",
  "to",
] as const;

function ByTypeChart({ agg, onPick, selected }: { agg: ErrorAggregations; onPick: (type: string) => void; selected: string[] }) {
  const rows = agg.by_type.slice(0, 12).map((r) => ({ ...r, name: r.label }));
  if (!rows.length) return <p className="py-8 text-center text-[13px] text-muted-foreground">Aucune erreur.</p>;
  const height = Math.max(160, rows.length * 32 + 24);
  return (
    <ChartContainer height={height} label={`Erreurs par type : ${rows.map((r) => `${r.label} ${r.count}`).join(", ")}`}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 4 }}>
        <CartesianGrid stroke="var(--chart-grid)" horizontal={false} />
        <XAxis type="number" allowDecimals={false} {...chartAxisProps} />
        <YAxis type="category" dataKey="name" width={150} {...chartAxisProps} tick={{ fill: "var(--foreground)", fontSize: 12 }} />
        <Tooltip
          cursor={chartCursor}
          content={({ active, payload }) => {
            const r = payload?.[0]?.payload as (typeof rows)[number] | undefined;
            if (!active || !r) return null;
            return (
              <div className="rounded-lg border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-lg">
                <p className="font-medium text-foreground">{r.label}</p>
                <p className="font-mono text-[11px] text-muted-foreground">{r.error_type}</p>
                <p className="mt-1 tabular-nums">
                  {formatNumber(r.count, 0)} occurrence{r.count > 1 ? "s" : ""} · {formatNumber(r.runs_affected, 0)} run{r.runs_affected > 1 ? "s" : ""}
                </p>
                <p className="mt-1 text-[11px] text-muted-foreground">Cliquer pour filtrer</p>
              </div>
            );
          }}
        />
        <Bar
          dataKey="count"
          name="Occurrences"
          radius={[0, 4, 4, 0]}
          maxBarSize={22}
          isAnimationActive={false}
          cursor="pointer"
          onClick={(d: unknown) => {
            const type = (d as { payload?: { error_type?: string } } | undefined)?.payload?.error_type;
            if (type) onPick(type);
          }}
        >
          {rows.map((r) => (
            <Cell key={r.error_type} fill={CHART_COLORS[0]} fillOpacity={selected.length && !selected.includes(r.error_type) ? 0.35 : 1} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}

function SeverityBreakdown({ agg, onPick }: { agg: ErrorAggregations; onPick: (s: ErrorSeverity) => void }) {
  const total = Object.values(agg.by_severity).reduce((s, v) => s + v, 0);
  const order = [...ERROR_SEVERITIES].reverse();
  return (
    <div className="grid gap-3">
      <div className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full bg-muted" aria-hidden>
        {order.map((s) => {
          const v = agg.by_severity[s] ?? 0;
          return v ? <span key={s} className={cn("h-full", toneClasses(ERROR_SEVERITY_META[s].tone).bar)} style={{ width: `${(v / Math.max(1, total)) * 100}%` }} /> : null;
        })}
      </div>
      <ul className="grid gap-1.5">
        {order.map((s) => {
          const v = agg.by_severity[s] ?? 0;
          return (
            <li key={s}>
              <button
                type="button"
                onClick={() => onPick(s)}
                className="flex w-full items-center justify-between gap-2 rounded-md px-1.5 py-1 text-[13px] hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <SeverityBadge severity={s} />
                <span className="tabular-nums">
                  <span className="font-medium">{formatNumber(v, 0)}</span>
                  <span className="ml-1.5 text-xs text-muted-foreground">{total ? formatPercent(v / total) : "—"}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function BarList({ rows, onPick, empty }: { rows: Array<{ key: string; label: string; sub?: string; count: number; runs: number }>; onPick: (key: string) => void; empty: string }) {
  if (!rows.length) return <p className="py-4 text-center text-[13px] text-muted-foreground">{empty}</p>;
  const max = Math.max(...rows.map((r) => r.count), 1);
  return (
    <ul className="grid gap-1">
      {rows.slice(0, 8).map((r) => (
        <li key={r.key}>
          <button
            type="button"
            onClick={() => onPick(r.key)}
            className="grid w-full gap-1 rounded-md px-1.5 py-1 text-left hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            title="Filtrer"
          >
            <span className="flex items-center justify-between gap-2 text-[13px]">
              <span className="truncate">{r.label}</span>
              <span className="shrink-0 tabular-nums">
                <span className="font-medium">{formatNumber(r.count, 0)}</span>
                <span className="ml-1.5 text-xs text-muted-foreground">{formatNumber(r.runs, 0)} run{r.runs > 1 ? "s" : ""}</span>
              </span>
            </span>
            <span className="h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
              <span className="block h-full rounded-full" style={{ width: `${(r.count / max) * 100}%`, backgroundColor: CHART_COLORS[0] }} />
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function runHref(item: ErrorItem): string {
  return item.trace_event_id ? `/runs/${item.run_id}?event_id=${item.trace_event_id}` : `/runs/${item.run_id}?section=errors`;
}

function ErrorsTable({ items }: { items: ErrorItem[] }) {
  return (
    <Table dense containerClassName="rounded-xl border border-border bg-card shadow-xs">
      <TableHeader>
        <TableRow>
          <TableHead>Type</TableHead>
          <TableHead>Gravité</TableHead>
          <TableHead className="min-w-[18rem]">Description</TableHead>
          <TableHead>Scénario</TableHead>
          <TableHead>Version d&apos;agent</TableHead>
          <TableHead>Détecté par</TableHead>
          <TableHead>Date</TableHead>
          <TableHead className="text-right">Run</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((e) => {
          const excerpt = Array.isArray(e.evidence) ? (e.evidence[0] as { excerpt?: string } | undefined)?.excerpt : undefined;
          return (
            <TableRow key={e.id}>
              <TableCell className="align-top">
                <ErrorTypeBadge code={e.error_type} label={e.label} />
              </TableCell>
              <TableCell className="align-top">
                <SeverityBadge severity={e.severity} />
              </TableCell>
              <TableCell className="align-top">
                {e.redacted ? (
                  <RedactedNotice variant="inline" title="Description masquée (scénario privé)" />
                ) : (
                  <div className="grid gap-1">
                    <span className="text-[13px] leading-snug">{truncate(e.description, 220)}</span>
                    {excerpt ? <span className="line-clamp-1 text-xs italic text-muted-foreground">« {excerpt} »</span> : null}
                    {e.criterion_key ? <span className="font-mono text-[11px] text-muted-foreground">{e.criterion_key}</span> : null}
                  </div>
                )}
              </TableCell>
              <TableCell className="max-w-[14rem] align-top">
                <div className="grid min-w-0 gap-0.5">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate font-medium">{e.scenario.name}</span>
                    {e.scenario.classification >= 2 ? <ClassificationBadge level={e.scenario.classification} showLabel={false} /> : null}
                  </span>
                  <span className="truncate text-[11px] text-muted-foreground">{SCENARIO_CATEGORIES[e.scenario.category] ?? e.scenario.category}</span>
                </div>
              </TableCell>
              <TableCell className="align-top">
                <div className="grid gap-0.5">
                  <span className="truncate">{e.agent_version.label}</span>
                  <RunOriginBadge value={e.origin} />
                </div>
              </TableCell>
              <TableCell className="align-top">
                <div className="grid gap-0.5">
                  {e.evaluator_kind ? <EvaluatorKindBadge value={e.evaluator_kind} withTooltip={false} /> : null}
                  <span className="font-mono text-[11px] text-muted-foreground">{e.evaluator_key}</span>
                </div>
              </TableCell>
              <TableCell className="align-top text-muted-foreground">
                <RelativeTime date={e.created_at} />
              </TableCell>
              <TableCell className="text-right align-top">
                <Button asChild variant="ghost" size="xs">
                  <Link href={runHref(e)} title={e.trace_event_id ? "Ouvrir le run sur l'événement de trace" : "Ouvrir le run"}>
                    {e.trace_event_id ? "Trace" : "Run"}
                    <ExternalLink aria-hidden />
                  </Link>
                </Button>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/** `/errors` — errors explorer: filters (URL-synced), aggregations and the paginated list. */
export function ErrorsExplorerView() {
  const search = useSearchState();
  const agentId = search.get("agent_id");
  const agents = useAgentOptions();
  const versions = useAgentVersionOptions(agentId);
  const scenarios = useScenarioOptions();
  const types = useErrorTypes();
  const page = Math.max(1, search.getNumber("page") ?? 1);
  const selectedTypes = search.getAll("type");
  const selectedSeverities = search.getAll("severity");

  const params: ErrorsParams = {
    page,
    page_size: DEFAULT_PAGE_SIZE,
    error_type: selectedTypes,
    severity: selectedSeverities,
    agent_id: agentId,
    agent_version_id: search.get("agent_version_id"),
    scenario_id: search.get("scenario_id"),
    category: search.get("category"),
    benchmark_execution_id: search.get("benchmark_execution_id"),
    experiment_id: search.get("experiment_id"),
    run_id: search.get("run_id"),
    date_from: dateInputToIso(search.get("from")),
    date_to: dateInputToIso(search.get("to"), true),
  };
  const errors = useErrorsExplorer(params);
  const data = errors.data;
  const agg = data?.aggregations;
  const activeCount = search.countActive(FILTER_KEYS);

  const toggleIn = (key: "type" | "severity", value: string) => {
    const current = search.getAll(key);
    search.set({ [key]: current.includes(value) ? current.filter((v) => v !== value) : [...current, value] });
  };

  const typeOptions = (types.data ?? []).map((t) => ({ value: t.code, label: t.label }));
  for (const code of selectedTypes) if (!typeOptions.some((o) => o.value === code)) typeOptions.push({ value: code, label: code });

  return (
    <>
      <PageHeader
        eyebrow="Analyser · Résultats"
        title="Erreurs détectées"
        icon={<Bug />}
        description="Toutes les erreurs détectées (règles, juges, exécution) : où, à quelle fréquence, avec quelle gravité et sur quelles versions d'agent."
      >
        <ResultsAreaTabs />
      </PageHeader>

      <FilterBar activeCount={activeCount} onReset={() => search.clear()} className="mb-4">
        <MultiFilter id="errors-type" label="Type d'erreur" values={selectedTypes} onChange={(type) => search.set({ type })} options={typeOptions} className="col-span-2" />
        <MultiFilter
          id="errors-severity"
          label="Gravité"
          values={selectedSeverities}
          onChange={(severity) => search.set({ severity })}
          options={enumOptions(ERROR_SEVERITIES, ERROR_SEVERITY_META)}
          allLabel="Toutes"
        />
        <FilterSelect
          id="errors-category"
          label="Catégorie"
          value={search.get("category")}
          onChange={(category) => search.set({ category })}
          options={Object.entries(SCENARIO_CATEGORIES).map(([value, label]) => ({ value, label }))}
          allLabel="Toutes"
        />
        <FilterSelect
          id="errors-agent"
          label="Agent"
          value={agentId}
          onChange={(v) => search.set({ agent_id: v, agent_version_id: undefined })}
          options={(agents.data?.items ?? []).map((a) => ({ value: a.id, label: a.name }))}
          loading={agents.isPending}
        />
        <FilterSelect
          id="errors-agent-version"
          label="Version d'agent"
          value={search.get("agent_version_id")}
          onChange={(v) => search.set({ agent_version_id: v })}
          options={[...(versions.data ?? [])].sort((a, b) => b.version_number - a.version_number).map((v) => ({ value: v.id, label: `v${v.version}` }))}
          disabled={!agentId && !search.get("agent_version_id")}
          allLabel={agentId ? "Toutes" : "Choisir un agent"}
        />
        <FilterSelect
          id="errors-scenario"
          label="Scénario"
          value={search.get("scenario_id")}
          onChange={(v) => search.set({ scenario_id: v })}
          options={(scenarios.data?.items ?? []).map((s) => ({ value: s.id, label: s.name, description: s.slug }))}
          loading={scenarios.isPending}
          className="col-span-2"
        />
        <SearchFilter id="errors-bench" label="Exécution de benchmark (id)" value={search.get("benchmark_execution_id")} onChange={(v) => search.set({ benchmark_execution_id: v })} placeholder="UUID…" />
        <SearchFilter id="errors-exp" label="Expérience (id)" value={search.get("experiment_id")} onChange={(v) => search.set({ experiment_id: v })} placeholder="UUID…" />
        <DateFilter id="errors-from" label="Du" value={search.get("from")} onChange={(from) => search.set({ from })} />
        <DateFilter id="errors-to" label="Au" value={search.get("to")} onChange={(to) => search.set({ to })} />
      </FilterBar>

      {search.get("run_id") ? (
        <div className="mb-3 flex items-center gap-2 text-xs text-muted-foreground">
          Filtré sur le run
          <Link href={`/runs/${search.get("run_id")}`} className="font-mono text-primary hover:underline">
            {search.get("run_id")?.slice(0, 8)}
          </Link>
          <Button variant="link" size="xs" onClick={() => search.set({ run_id: undefined })}>
            Retirer
          </Button>
        </div>
      ) : null}

      {errors.isError && !data ? (
        <ErrorState error={errors.error} onRetry={() => void errors.refetch()} />
      ) : (
        <div className={cn("grid gap-4", errors.isPlaceholderData && "opacity-60")} aria-busy={errors.isFetching}>
          <section aria-label="Indicateurs" className="grid gap-3 sm:grid-cols-3">
            <KpiCard label="Erreurs" icon={<Bug />} value={formatNumber(agg?.total ?? 0, 0)} loading={errors.isPending} />
            <KpiCard label="Runs concernés" icon={<Play />} tone="blue" value={formatNumber(agg?.runs_affected ?? 0, 0)} loading={errors.isPending} />
            <KpiCard
              label="Erreurs critiques"
              icon={<OctagonAlert />}
              tone="red"
              value={formatNumber(agg?.critical ?? 0, 0)}
              loading={errors.isPending}
              hint={agg && agg.total ? `${formatPercent(agg.critical / agg.total)} du total` : undefined}
            />
          </section>

          {errors.isPending ? (
            <div className="grid gap-4 lg:grid-cols-3">
              <Skeleton className="h-64 rounded-xl lg:col-span-2" />
              <Skeleton className="h-64 rounded-xl" />
            </div>
          ) : agg && agg.total > 0 ? (
            <div className="grid gap-4 lg:grid-cols-3">
              <Card className="lg:col-span-2">
                <CardHeader className="pb-2">
                  <CardTitle>Par type</CardTitle>
                  <CardDescription>Occurrences par type de la taxonomie ; cliquez sur une barre pour filtrer.</CardDescription>
                </CardHeader>
                <CardContent>
                  <ByTypeChart agg={agg} selected={selectedTypes} onPick={(t) => toggleIn("type", t)} />
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle>Par gravité</CardTitle>
                </CardHeader>
                <CardContent>
                  <SeverityBreakdown agg={agg} onPick={(s) => toggleIn("severity", s)} />
                </CardContent>
              </Card>
              <Card className="lg:col-span-1">
                <CardHeader className="pb-2">
                  <CardTitle>Par version d&apos;agent</CardTitle>
                </CardHeader>
                <CardContent>
                  <BarList
                    rows={agg.by_agent_version.map((r) => ({ key: r.agent_version_id, label: r.label, count: r.count, runs: r.runs_affected }))}
                    onPick={(id) => search.set({ agent_version_id: id })}
                    empty="Aucune version."
                  />
                </CardContent>
              </Card>
              <Card className="lg:col-span-2">
                <CardHeader className="pb-2">
                  <CardTitle>Par scénario</CardTitle>
                </CardHeader>
                <CardContent>
                  <BarList
                    rows={agg.by_scenario.map((r) => ({ key: r.scenario_id, label: r.name, sub: r.slug, count: r.count, runs: r.runs_affected }))}
                    onPick={(id) => search.set({ scenario_id: id })}
                    empty="Aucun scénario."
                  />
                </CardContent>
              </Card>
            </div>
          ) : null}

          {!errors.isPending && data && data.items.length === 0 ? (
            <EmptyState
              icon={<Inbox />}
              title={activeCount ? "Aucune erreur pour ces filtres" : "Aucune erreur détectée"}
              description={activeCount ? "Élargissez les filtres pour retrouver des erreurs." : "Les erreurs détectées par les règles, les juges et l'exécution apparaîtront ici."}
              action={
                activeCount ? (
                  <Button variant="secondary" size="sm" onClick={() => search.clear()}>
                    Réinitialiser les filtres
                  </Button>
                ) : null
              }
            />
          ) : data ? (
            <div className="grid gap-3">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold">Liste des erreurs</h2>
                <Badge tone="neutral">{formatNumber(data.total, 0)}</Badge>
              </div>
              <ErrorsTable items={data.items} />
              <Pagination page={page} pageSize={data.page_size} total={data.total} onPageChange={(p) => search.set({ page: p > 1 ? p : undefined })} disabled={errors.isFetching} />
            </div>
          ) : null}
        </div>
      )}
    </>
  );
}
