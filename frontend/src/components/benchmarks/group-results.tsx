"use client";

import * as React from "react";

import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { CostDisplay, DurationDisplay, TokenCount } from "@/components/domain/metric-display";
import { ScoreBadge } from "@/components/domain/score-badge";
import { SeverityBadge } from "@/components/domain/severity-badge";
import { Alert } from "@/components/ui/alert";
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { SimpleSelect } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { GROUP_BY_OPTIONS, useBenchmarkResults, type BenchmarkResults, type GroupBy } from "@/lib/api/benchmarks";
import { isEnumValue, SCENARIO_CATEGORIES, scenarioCategoryLabel } from "@/lib/enums";
import { formatInterval, formatNumber, formatPercent, formatScore100 } from "@/lib/format";
import { CiBar } from "./leaderboard";
import { useUrlState } from "./use-url-state";

const GROUP_VALUES = GROUP_BY_OPTIONS.map((o) => o.value);
const ALL = "__all__";

function ErrorsTable({ results }: { results: BenchmarkResults }) {
  const agentIds = Object.keys(results.agents);
  return (
    <Table dense>
      <TableHeader>
        <TableRow>
          <TableHead>Type d&apos;erreur</TableHead>
          <TableHead>Gravité max.</TableHead>
          <TableHead className="text-right">Occurrences</TableHead>
          <TableHead className="text-right">Runs touchés</TableHead>
          {agentIds.map((id) => (
            <TableHead key={id} className="text-right normal-case">
              {results.agents[id]}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {results.errors.length === 0 ? (
          <TableEmptyRow colSpan={4 + agentIds.length}>Aucune erreur détectée.</TableEmptyRow>
        ) : (
          results.errors.map((e) => (
            <TableRow key={e.error_type}>
              <TableCell>
                <ErrorTypeBadge code={e.error_type} />
              </TableCell>
              <TableCell>
                <SeverityBadge severity={e.max_severity} />
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(e.count, 0)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(e.runs_affected, 0)}</TableCell>
              {agentIds.map((id) => (
                <TableCell key={id} className="text-right tabular-nums">
                  {e.by_agent[id] ?? 0}
                </TableCell>
              ))}
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}

/** Results of `GET /benchmarks/{id}/results` with a URL-synced group-by switcher and filters. */
export function GroupResults({ benchmarkId, executionId, live }: { benchmarkId: string; executionId: string; live: boolean }) {
  const { get, set } = useUrlState();
  const rawGroup = get("group_by");
  const groupBy: GroupBy = isEnumValue(GROUP_VALUES, rawGroup) ? rawGroup : "version";
  const visibility = get("visibility") ?? undefined;
  const category = get("category") ?? undefined;
  const query = useBenchmarkResults(benchmarkId, { execution_id: executionId, group_by: groupBy, visibility, category }, { live });
  const results = query.data;
  const refetch = query.refetch;
  const wasLive = React.useRef(live);
  React.useEffect(() => {
    if (wasLive.current && !live) void refetch();
    wasLive.current = live;
  }, [live, refetch]);
  const agentIds = results ? Object.keys(results.agents) : [];
  const showByAgent = groupBy !== "version" && groupBy !== "agent" && agentIds.length > 1;

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="flex-row flex-wrap items-start gap-3">
          <div className="grid gap-1">
            <CardTitle>Résultats regroupés</CardTitle>
            <CardDescription>Composite moyen (IC 95 %), réussite, garde-fous, coûts et latences par groupe.</CardDescription>
          </div>
          <CardAction className="flex-wrap">
            {query.isFetching ? <Spinner /> : null}
            <SimpleSelect
              size="sm"
              className="w-44"
              aria-label="Regrouper par"
              value={groupBy}
              options={GROUP_BY_OPTIONS}
              onValueChange={(v) => set({ group_by: v === "version" ? null : v })}
            />
            <SimpleSelect
              size="sm"
              className="w-36"
              aria-label="Visibilité"
              value={visibility ?? ALL}
              options={[
                { value: ALL, label: "Toutes visibilités" },
                { value: "public", label: "Publics" },
                { value: "private", label: "Privés" },
                { value: "fresh", label: "Fresh" },
              ]}
              onValueChange={(v) => set({ visibility: v === ALL ? null : v })}
            />
            <SimpleSelect
              size="sm"
              className="w-44"
              aria-label="Catégorie"
              value={category ?? ALL}
              options={[
                { value: ALL, label: "Toutes catégories" },
                ...Object.keys(SCENARIO_CATEGORIES).map((k) => ({ value: k, label: scenarioCategoryLabel(k) })),
              ]}
              onValueChange={(v) => set({ category: v === ALL ? null : v })}
            />
          </CardAction>
        </CardHeader>
        {results?.restricted ? (
          <div className="px-5 pb-3">
            <Alert tone="amber">Résultats limités aux scénarios couverts par votre habilitation.</Alert>
          </div>
        ) : null}
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} variant="plain" size="sm" />
        ) : !results ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : groupBy === "error_type" ? (
          <ErrorsTable results={results} />
        ) : (
          <Table dense>
            <TableHeader>
              <TableRow>
                <TableHead>{GROUP_BY_OPTIONS.find((o) => o.value === groupBy)?.label}</TableHead>
                <TableHead className="text-right">Runs</TableHead>
                <TableHead>Composite · IC 95 %</TableHead>
                <TableHead className="text-right">Réussite</TableHead>
                <TableHead className="text-right">Garde-fou</TableHead>
                <TableHead className="text-right">Coût moy.</TableHead>
                <TableHead className="text-right">Latence moy.</TableHead>
                <TableHead className="text-right">Tokens moy.</TableHead>
                <TableHead className="text-right">Erreurs</TableHead>
                {showByAgent
                  ? agentIds.map((id) => (
                      <TableHead key={id} className="text-right normal-case">
                        {results.agents[id]}
                      </TableHead>
                    ))
                  : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {results.rows.length === 0 ? (
                <TableEmptyRow colSpan={9 + (showByAgent ? agentIds.length : 0)}>Aucun run ne correspond à ces filtres.</TableEmptyRow>
              ) : (
                results.rows.map((r) => (
                  <TableRow key={r.key}>
                    <TableCell className="font-medium">{groupBy === "category" ? scenarioCategoryLabel(r.label) : r.label}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.n_scored}/{r.n_runs}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <ScoreBadge value={r.composite_mean} />
                        <CiBar mean={r.composite_mean} low={r.composite_ci_low} high={r.composite_ci_high} width={72} />
                        <span className="text-[11px] tabular-nums text-muted-foreground">
                          {formatInterval(r.composite_ci_low, r.composite_ci_high)}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatPercent(r.pass_rate)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatPercent(r.gate_failure_rate)}</TableCell>
                    <TableCell className="text-right">
                      <CostDisplay value={r.cost_mean} />
                    </TableCell>
                    <TableCell className="text-right">
                      <DurationDisplay ms={r.latency_mean} />
                    </TableCell>
                    <TableCell className="text-right">
                      <TokenCount total={r.tokens_mean} unit={false} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.error_count}
                      <span className="block text-[11px] text-muted-foreground">{r.runs_with_errors} run(s)</span>
                    </TableCell>
                    {showByAgent
                      ? agentIds.map((id) => (
                          <TableCell key={id} className="text-right tabular-nums">
                            {formatScore100(r.by_agent?.[id])}
                          </TableCell>
                        ))
                      : null}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
      </Card>
      {results && groupBy !== "error_type" ? (
        <Card>
          <CardHeader>
            <CardTitle>Erreurs par type</CardTitle>
            <CardDescription>Occurrences par version d&apos;agent sur les runs filtrés.</CardDescription>
          </CardHeader>
          <ErrorsTable results={results} />
        </Card>
      ) : null}
    </div>
  );
}
