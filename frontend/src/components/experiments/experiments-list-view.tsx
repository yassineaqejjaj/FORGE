"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, FlaskConical, Plus, Search } from "lucide-react";

import { RequireRole } from "@/components/auth/require-role";
import { RunsProgress, TableSkeleton } from "@/components/benchmarks/common";
import { pageFrom, useUrlSearch, useUrlState } from "@/components/benchmarks/use-url-state";
import { DeltaIndicator } from "@/components/domain/delta-indicator";
import { RelativeTime } from "@/components/domain/relative-time";
import { ExecutionStatusBadge } from "@/components/domain/status-badge";
import { RecommendationBadge } from "@/components/domain/verdict-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { isActiveExecution } from "@/lib/api/benchmarks";
import { useExperiments } from "@/lib/api/experiments";
import { EXECUTION_STATUS_META, EXECUTION_STATUSES, RECOMMENDATION_META, RECOMMENDATIONS } from "@/lib/enums";
import { ExperimentFormDialog } from "./experiment-form-dialog";

const PAGE_SIZE = 25;
const ALL = "__all__";

export function ExperimentsListView() {
  const router = useRouter();
  const { get, set } = useUrlState();
  const search = useUrlSearch("q");
  const page = pageFrom(get("page"));
  const status = get("status") ?? undefined;
  const recommendation = get("recommendation") ?? undefined;
  const createOpen = get("new") === "1";

  const query = useExperiments({
    page,
    page_size: PAGE_SIZE,
    search: search.applied || undefined,
    status,
    recommendation,
    benchmark_id: get("benchmark_id") ?? undefined,
    agent_id: get("agent_id") ?? undefined,
  });
  const items = query.data?.items ?? [];
  const filtered = Boolean(search.applied || status || recommendation);

  return (
    <>
      <PageHeader
        eyebrow="Améliorer"
        title="Expériences"
        icon={<FlaskConical />}
        description="Baseline vs candidate sur les mêmes scénarios : la candidate est-elle réellement meilleure ? Deltas appariés avec IC 95 %, régressions, coûts et recommandation."
        actions={
          <RequireRole min="editor">
            <Button leftIcon={<Plus aria-hidden />} onClick={() => set({ new: "1" })}>
              Nouvelle expérience
            </Button>
          </RequireRole>
        }
      />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <Input
            size="sm"
            leftIcon={<Search aria-hidden />}
            placeholder="Rechercher une expérience…"
            value={search.value}
            onChange={(e) => search.setValue(e.target.value)}
            className="w-full sm:w-72"
            aria-label="Rechercher une expérience"
          />
          <SimpleSelect
            size="sm"
            className="w-44"
            aria-label="Statut"
            value={status ?? ALL}
            options={[
              { value: ALL, label: "Tous les statuts" },
              ...EXECUTION_STATUSES.filter((s) => s !== "draft").map((s) => ({ value: s, label: EXECUTION_STATUS_META[s].label })),
            ]}
            onValueChange={(v) => set({ status: v === ALL ? null : v, page: null })}
          />
          <SimpleSelect
            size="sm"
            className="w-52"
            aria-label="Recommandation"
            value={recommendation ?? ALL}
            options={[
              { value: ALL, label: "Toutes les recommandations" },
              ...RECOMMENDATIONS.map((r) => ({ value: r, label: RECOMMENDATION_META[r].label })),
            ]}
            onValueChange={(v) => set({ recommendation: v === ALL ? null : v, page: null })}
          />
          {get("benchmark_id") || get("agent_id") ? (
            <Button variant="ghost" size="sm" onClick={() => set({ benchmark_id: null, agent_id: null, page: null })}>
              Retirer le filtre de contexte
            </Button>
          ) : null}
        </div>
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} variant="plain" />
        ) : query.isPending ? (
          <TableSkeleton />
        ) : items.length === 0 && !filtered ? (
          <EmptyState
            variant="plain"
            icon={<FlaskConical />}
            title="Aucune expérience"
            description="Une expérience compare une version candidate à la baseline en production et bloque les régressions en CI."
            action={
              <RequireRole min="editor">
                <Button size="sm" leftIcon={<Plus aria-hidden />} onClick={() => set({ new: "1" })}>
                  Créer une expérience
                </Button>
              </RequireRole>
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Expérience</TableHead>
                <TableHead className="hidden lg:table-cell">Baseline → candidate</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead>Recommandation</TableHead>
                <TableHead className="text-right">Δ composite</TableHead>
                <TableHead className="hidden md:table-cell">Créée</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 ? (
                <TableEmptyRow colSpan={6}>Aucune expérience ne correspond à ces filtres.</TableEmptyRow>
              ) : (
                items.map((x) => (
                  <TableRow
                    key={x.id}
                    interactive
                    tabIndex={0}
                    onClick={() => router.push(`/experiments/${x.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") router.push(`/experiments/${x.id}`);
                    }}
                  >
                    <TableCell>
                      <div className="grid gap-0.5">
                        <Link href={`/experiments/${x.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                          {x.name}
                        </Link>
                        <span className="text-xs text-muted-foreground">
                          {x.benchmark_name ? `Benchmark ${x.benchmark_name}` : `${x.n_scenarios} scénario(s)`} · {x.repetitions} rép.
                          {x.warnings?.length ? (
                            <Badge tone="amber" className="ml-2">
                              {x.warnings?.length} avertissement(s)
                            </Badge>
                          ) : null}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="hidden lg:table-cell">
                      <span className="inline-flex items-center gap-1.5 text-[13px]">
                        <span className="text-muted-foreground">{x.baseline?.label ?? "—"}</span>
                        <ArrowRight className="size-3.5 text-subtle-foreground" aria-hidden />
                        <span className="font-medium">{x.candidate?.label ?? "—"}</span>
                      </span>
                    </TableCell>
                    <TableCell>
                      {isActiveExecution(x.status) ? (
                        <div className="grid gap-1">
                          <ExecutionStatusBadge status={x.status} />
                          <RunsProgress className="w-36" completed={x.completed_runs} failed={x.failed_runs} total={x.total_runs} active />
                        </div>
                      ) : (
                        <ExecutionStatusBadge status={x.status} detail={x.error} />
                      )}
                    </TableCell>
                    <TableCell>
                      {x.recommendation ? (
                        <RecommendationBadge recommendation={x.recommendation} size="sm" />
                      ) : (
                        <span className="text-xs text-subtle-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <DeltaIndicator value={x.composite_delta} unit="pts" />
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <RelativeTime date={x.created_at} className="text-xs text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
        {query.data && query.data.total > PAGE_SIZE ? (
          <div className="border-t border-border p-3">
            <Pagination page={page} pageSize={PAGE_SIZE} total={query.data.total} onPageChange={(p) => set({ page: p > 1 ? p : null })} />
          </div>
        ) : null}
      </Card>
      <ExperimentFormDialog
        open={createOpen}
        onOpenChange={(o) => {
          if (!o) set({ new: null, benchmark: null, baseline: null, candidate: null, feedback: null });
        }}
        defaults={{
          benchmarkId: get("benchmark"),
          baselineVersionId: get("baseline"),
          candidateVersionId: get("candidate"),
          sourceFeedbackReportId: get("feedback"),
        }}
      />
    </>
  );
}
