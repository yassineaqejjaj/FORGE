"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ArrowDown, ArrowUp, ArrowUpDown, Bug, Inbox, Play, Plus, ShieldX } from "lucide-react";

import { RequireRole } from "@/components/auth/require-role";
import { LocalTabs } from "@/components/layout/local-tabs";
import { ALL_NAV_ITEMS, isViewActive } from "@/components/layout/nav";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { CostDisplay, DurationDisplay, TokenCount } from "@/components/domain/metric-display";
import { RelativeTime } from "@/components/domain/relative-time";
import { ScoreBadge } from "@/components/domain/score-badge";
import { RunStatusBadge } from "@/components/domain/status-badge";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DEFAULT_PAGE_SIZE } from "@/lib/api/types";
import {
  isRunActive,
  useAgentOptions,
  useAgentVersionOptions,
  useRuns,
  useScenarioOptions,
  type Run,
  type RunListParams,
  type RunSort,
} from "@/lib/api/runs";
import { BUILTIN_ERROR_TYPE_META, enumOptions, RUN_ORIGIN_META, RUN_ORIGINS, RUN_STATUS_META, RUN_STATUSES, type BuiltinErrorType } from "@/lib/enums";
import { cn } from "@/lib/utils";
import { DateFilter, FilterBar, FilterSelect, MultiFilter, NumberFilter, SearchFilter } from "./filter-controls";
import { NewRunDialog } from "./new-run-dialog";
import { RunOrigin } from "./run-origin";
import { dateInputToIso, useSearchState } from "./use-search-state";

const FILTER_KEYS = [
  "q",
  "status",
  "origin",
  "agent_id",
  "agent_version_id",
  "scenario_id",
  "benchmark_execution_id",
  "experiment_id",
  "passed",
  "gate_failed",
  "min",
  "max",
  "from",
  "to",
] as const;

/** Status views of the list (same links as the mobile menu shortcuts). */
const RUNS_VIEWS = ALL_NAV_ITEMS.find((item) => item.href === "/runs")?.children ?? [];

const SORTS: ReadonlyArray<RunSort> = ["-created_at", "created_at", "-composite", "composite", "-latency", "latency"];

function SortHeader({
  label,
  field,
  sort,
  onSort,
  className,
}: {
  label: string;
  field: "created_at" | "composite" | "latency";
  sort: RunSort;
  onSort: (sort: RunSort) => void;
  className?: string;
}) {
  const active = sort.replace("-", "") === field;
  const desc = sort.startsWith("-");
  const Icon = !active ? ArrowUpDown : desc ? ArrowDown : ArrowUp;
  return (
    <TableHead className={className} aria-sort={active ? (desc ? "descending" : "ascending") : "none"}>
      <button
        type="button"
        onClick={() => onSort((active && desc ? field : `-${field}`) as RunSort)}
        className={cn(
          "-mx-1 inline-flex items-center gap-1 rounded px-1 uppercase tracking-wide hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          active && "text-foreground",
        )}
      >
        {label}
        <Icon className="size-3" aria-hidden />
      </button>
    </TableHead>
  );
}

function ResultCell({ run }: { run: Run }) {
  if (run.gate_failed)
    return (
      <Badge tone="red" variant="solid" icon={<ShieldX aria-hidden />}>
        Garde-fou
      </Badge>
    );
  if (run.passed === true) return <Badge tone="green" dot>Réussi</Badge>;
  if (run.passed === false) return <Badge tone="amber" dot>Sous le seuil</Badge>;
  return <span className="text-subtle-foreground">—</span>;
}

function statusDetail(run: Run): string | null {
  const parts = [run.status_detail];
  if (run.error_type) {
    const meta = BUILTIN_ERROR_TYPE_META[run.error_type as BuiltinErrorType];
    parts.push(meta ? `${meta.label} (${run.error_type})` : run.error_type);
  }
  return parts.filter(Boolean).join(" · ") || null;
}

function RunsTable({ runs, loading }: { runs: Run[]; loading: boolean; }) {
  const router = useRouter();
  const search = useSearchState();
  const sort = (SORTS as readonly string[]).includes(search.get("sort") ?? "") ? (search.get("sort") as RunSort) : "-created_at";
  const onSort = (s: RunSort) => search.set({ sort: s === "-created_at" ? undefined : s });

  return (
    <Table dense containerClassName="rounded-xl border border-border bg-card shadow-xs">
      <TableHeader>
        <TableRow>
          <TableHead>Scénario</TableHead>
          <TableHead>Version d&apos;agent</TableHead>
          <TableHead>Statut</TableHead>
          <SortHeader label="Score" field="composite" sort={sort} onSort={onSort} />
          <TableHead>Résultat</TableHead>
          <TableHead className="text-right">Coût</TableHead>
          <SortHeader label="Latence" field="latency" sort={sort} onSort={onSort} className="text-right" />
          <TableHead className="text-right">Tokens</TableHead>
          <TableHead>Origine</TableHead>
          <TableHead className="text-right">Rép.</TableHead>
          <SortHeader label="Créé" field="created_at" sort={sort} onSort={onSort} />
        </TableRow>
      </TableHeader>
      <TableBody>
        {loading
          ? Array.from({ length: 8 }, (_, i) => (
              <TableRow key={i}>
                {Array.from({ length: 11 }, (__, j) => (
                  <TableCell key={j}>
                    <Skeleton className={cn("h-4", j === 0 ? "w-44" : "w-14")} />
                  </TableCell>
                ))}
              </TableRow>
            ))
          : runs.map((run) => (
              <TableRow
                key={run.id}
                interactive
                onClick={(e) => {
                  if ((e.target as HTMLElement).closest("a,button")) return;
                  router.push(`/runs/${run.id}`);
                }}
              >
                <TableCell className="max-w-[20rem]">
                  <div className="flex min-w-0 items-center gap-2">
                    <VisibilityBadge visibility={run.visibility} iconOnly noTooltip />
                    <div className="grid min-w-0">
                      <Link
                        href={`/runs/${run.id}`}
                        className="truncate font-medium text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        {run.scenario_name}
                      </Link>
                      <span className="truncate font-mono text-[11px] text-muted-foreground">
                        {run.scenario_slug}
                        {run.scenario_version ? ` · v${run.scenario_version}` : ""}
                      </span>
                    </div>
                    {run.classification >= 2 ? <ClassificationBadge level={run.classification} showLabel={false} /> : null}
                  </div>
                </TableCell>
                <TableCell className="max-w-[14rem]">
                  <div className="grid min-w-0">
                    <span className="truncate">{run.agent_label ?? run.agent_name ?? "—"}</span>
                    {run.model ? <span className="truncate text-[11px] text-muted-foreground">{run.model}</span> : null}
                  </div>
                </TableCell>
                <TableCell>
                  <RunStatusBadge status={run.status} detail={statusDetail(run)} />
                </TableCell>
                <TableCell>
                  <ScoreBadge value={run.composite_score} passed={run.passed} gateFailed={run.gate_failed} />
                </TableCell>
                <TableCell>
                  <ResultCell run={run} />
                </TableCell>
                <TableCell className="text-right">
                  <CostDisplay value={run.cost} muted />
                </TableCell>
                <TableCell className="text-right">
                  <DurationDisplay ms={run.latency_ms} muted />
                </TableCell>
                <TableCell className="text-right">
                  <TokenCount total={run.total_tokens} unit={false} muted />
                </TableCell>
                <TableCell>
                  <RunOrigin
                    origin={run.origin}
                    benchmarkExecutionId={run.benchmark_execution_id}
                    experimentId={run.experiment_id}
                    arm={run.arm}
                  />
                </TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">{run.repetition}</TableCell>
                <TableCell className="text-muted-foreground">
                  <RelativeTime date={run.created_at} />
                </TableCell>
              </TableRow>
            ))}
      </TableBody>
    </Table>
  );
}

function boolParam(v: string | undefined): boolean | undefined {
  return v === "true" ? true : v === "false" ? false : undefined;
}

/** `/runs` (« Exécutions »): status views, filterable, sortable, paginated list (URL-synced). */
export function RunsListView() {
  const search = useSearchState();
  const [dialogOpen, setDialogOpen] = React.useState(false);

  const agentId = search.get("agent_id");
  const agents = useAgentOptions();
  const versions = useAgentVersionOptions(agentId);
  const scenarios = useScenarioOptions();

  const page = Math.max(1, search.getNumber("page") ?? 1);
  const sortParam = search.get("sort");
  const params: RunListParams = {
    page,
    page_size: DEFAULT_PAGE_SIZE,
    q: search.get("q"),
    status: search.getAll("status"),
    origin: search.get("origin"),
    agent_id: agentId,
    agent_version_id: search.get("agent_version_id"),
    scenario_id: search.get("scenario_id"),
    benchmark_execution_id: search.get("benchmark_execution_id"),
    experiment_id: search.get("experiment_id"),
    passed: boolParam(search.get("passed")),
    gate_failed: boolParam(search.get("gate_failed")),
    min_composite: search.getNumber("min"),
    max_composite: search.getNumber("max"),
    created_from: dateInputToIso(search.get("from")),
    created_to: dateInputToIso(search.get("to"), true),
    sort: (SORTS as readonly string[]).includes(sortParam ?? "") ? (sortParam as RunSort) : undefined,
  };
  const runs = useRuns(params);
  const activeCount = search.countActive(FILTER_KEYS);
  const items = runs.data?.items ?? [];
  const liveCount = items.filter((r) => isRunActive(r.status)).length;

  const resultValue = search.get("gate_failed") === "true" ? "gate" : search.get("passed");
  const pathname = usePathname();
  const views = RUNS_VIEWS.map((view) => ({
    href: view.href,
    label: view.label,
    active: isViewActive(pathname, search.params, view.href) && !search.get("gate_failed"),
  }));

  return (
    <>
      <PageHeader
        eyebrow="Tester"
        title="Exécutions"
        icon={<Play />}
        description="Chaque exécution d'un agent sur un scénario : trace, sortie, scores expliqués, erreurs et feedback."
        meta={
          liveCount > 0 ? (
            <Badge tone="blue" pulse>
              {liveCount} en cours · actualisation automatique
            </Badge>
          ) : null
        }
        actions={
          <>
            <Button asChild variant="secondary">
              <Link href="/errors">
                <Bug aria-hidden />
                Erreurs détectées
              </Link>
            </Button>
            <RequireRole min="editor">
              <Button leftIcon={<Plus aria-hidden />} onClick={() => setDialogOpen(true)}>
                Nouvelle exécution
              </Button>
            </RequireRole>
          </>
        }
      >
        <LocalTabs
          label="Vues des exécutions"
          tabs={views}
          onSelect={(tab, event) => {
            // Keep the other filters (agent, scenario, dates…): only the view keys change.
            event.preventDefault();
            const target = new URLSearchParams(tab.href.split("?")[1] ?? "");
            search.set({
              status: target.getAll("status"),
              passed: target.get("passed"),
              gate_failed: undefined,
            });
          }}
        />
      </PageHeader>

      <FilterBar activeCount={activeCount} onReset={() => search.clear(["sort"])} className="mb-4">
        <SearchFilter
          id="runs-q"
          label="Recherche"
          value={search.get("q")}
          onChange={(q) => search.set({ q })}
          placeholder="Scénario ou agent…"
          className="col-span-2"
        />
        <MultiFilter
          id="runs-status"
          label="Statut"
          values={search.getAll("status")}
          onChange={(status) => search.set({ status })}
          options={enumOptions(RUN_STATUSES, RUN_STATUS_META)}
        />
        <FilterSelect
          id="runs-origin"
          label="Origine"
          value={search.get("origin")}
          onChange={(origin) => search.set({ origin })}
          options={enumOptions(RUN_ORIGINS, RUN_ORIGIN_META)}
          allLabel="Toutes"
        />
        <FilterSelect
          id="runs-result"
          label="Résultat"
          value={resultValue}
          onChange={(v) =>
            search.set({ passed: v === "true" || v === "false" ? v : undefined, gate_failed: v === "gate" ? "true" : undefined })
          }
          options={[
            { value: "true", label: "Réussis" },
            { value: "false", label: "Échoués (sous le seuil ou garde-fou)" },
            { value: "gate", label: "Garde-fou en échec" },
          ]}
        />
        <FilterSelect
          id="runs-agent"
          label="Agent"
          value={agentId}
          onChange={(v) => search.set({ agent_id: v, agent_version_id: undefined })}
          options={(agents.data?.items ?? []).map((a) => ({ value: a.id, label: a.name }))}
          loading={agents.isPending}
        />
        <FilterSelect
          id="runs-agent-version"
          label="Version d'agent"
          value={search.get("agent_version_id")}
          onChange={(v) => search.set({ agent_version_id: v })}
          options={[...(versions.data ?? [])]
            .sort((a, b) => b.version_number - a.version_number)
            .map((v) => ({ value: v.id, label: `v${v.version}`, description: v.model ?? undefined }))}
          disabled={!agentId && !search.get("agent_version_id")}
          allLabel={agentId ? "Toutes" : "Choisir un agent"}
          loading={versions.isFetching}
        />
        <FilterSelect
          id="runs-scenario"
          label="Scénario"
          value={search.get("scenario_id")}
          onChange={(v) => search.set({ scenario_id: v })}
          options={(scenarios.data?.items ?? []).map((s) => ({ value: s.id, label: s.name, description: s.slug }))}
          loading={scenarios.isPending}
        />
        <NumberFilter id="runs-min" label="Score min." value={search.getNumber("min")} onChange={(min) => search.set({ min })} min={0} max={100} placeholder="0" />
        <NumberFilter id="runs-max" label="Score max." value={search.getNumber("max")} onChange={(max) => search.set({ max })} min={0} max={100} placeholder="100" />
        <DateFilter id="runs-from" label="Créé à partir du" value={search.get("from")} onChange={(from) => search.set({ from })} />
        <DateFilter id="runs-to" label="Créé jusqu'au" value={search.get("to")} onChange={(to) => search.set({ to })} />
      </FilterBar>

      {search.get("benchmark_execution_id") || search.get("experiment_id") ? (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>Filtré sur</span>
          {search.get("benchmark_execution_id") ? (
            <Badge tone="blue" variant="outline">
              Exécution de benchmark {search.get("benchmark_execution_id")?.slice(0, 8)}
            </Badge>
          ) : null}
          {search.get("experiment_id") ? (
            <Badge tone="violet" variant="outline">
              Expérience {search.get("experiment_id")?.slice(0, 8)}
            </Badge>
          ) : null}
          <Button variant="link" size="xs" onClick={() => search.set({ benchmark_execution_id: undefined, experiment_id: undefined })}>
            Retirer
          </Button>
        </div>
      ) : null}

      {runs.isError && !runs.data ? (
        <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
      ) : !runs.isPending && items.length === 0 ? (
        <EmptyState
          icon={<Inbox />}
          title={activeCount ? "Aucune exécution ne correspond à ces filtres" : "Aucune exécution pour l'instant"}
          description={
            activeCount
              ? "Élargissez la recherche ou réinitialisez les filtres."
              : "Lancez une version d'agent sur des scénarios pour obtenir une trace, des scores expliqués et un feedback."
          }
          action={
            activeCount ? (
              <Button variant="secondary" size="sm" onClick={() => search.clear(["sort"])}>
                Réinitialiser les filtres
              </Button>
            ) : (
              <RequireRole min="editor">
                <Button size="sm" leftIcon={<Plus aria-hidden />} onClick={() => setDialogOpen(true)}>
                  Nouvelle exécution
                </Button>
              </RequireRole>
            )
          }
        />
      ) : (
        <div className={cn("grid gap-3 transition-opacity", runs.isPlaceholderData && "opacity-60")} aria-busy={runs.isFetching}>
          <RunsTable runs={items} loading={runs.isPending} />
          {runs.data ? (
            <Pagination
              page={page}
              pageSize={runs.data.page_size}
              total={runs.data.total}
              onPageChange={(p) => search.set({ page: p > 1 ? p : undefined })}
              disabled={runs.isFetching}
            />
          ) : null}
        </div>
      )}

      <NewRunDialog open={dialogOpen} onOpenChange={setDialogOpen} defaultAgentId={agentId} />
    </>
  );
}
