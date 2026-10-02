"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Layers, Plus, Search } from "lucide-react";

import { RequireRole } from "@/components/auth/require-role";
import { RelativeTime } from "@/components/domain/relative-time";
import { ExecutionStatusBadge } from "@/components/domain/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { isActiveExecution, useBenchmarks } from "@/lib/api/benchmarks";
import { formatNumber } from "@/lib/format";
import { BenchmarkFormDialog } from "./benchmark-form-dialog";
import { RunsProgress, TableSkeleton } from "./common";
import { pageFrom, useUrlSearch, useUrlState } from "./use-url-state";

const PAGE_SIZE = 25;

export function BenchmarksListView() {
  const router = useRouter();
  const { get, set } = useUrlState();
  const search = useUrlSearch("q");
  const page = pageFrom(get("page"));
  const archived = get("archived") === "true";
  const [createOpen, setCreateOpen] = React.useState(get("new") === "1");

  const query = useBenchmarks({ page, page_size: PAGE_SIZE, search: search.applied || undefined, archived });
  const items = query.data?.items ?? [];

  return (
    <>
      <PageHeader
        eyebrow="Analyser"
        title="Comparaisons"
        icon={<Layers />}
        description="Comparez plusieurs versions d'agents sur les mêmes scénarios (benchmarks) : classements avec IC 95 %, robustesse, coûts, latences et écart de généralisation."
        actions={
          <RequireRole min="editor">
            <Button leftIcon={<Plus aria-hidden />} onClick={() => setCreateOpen(true)}>
              Nouvelle comparaison
            </Button>
          </RequireRole>
        }
      />

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <Input
            size="sm"
            leftIcon={<Search aria-hidden />}
            placeholder="Rechercher par nom ou slug…"
            value={search.value}
            onChange={(e) => search.setValue(e.target.value)}
            className="w-full sm:w-72"
            aria-label="Rechercher un benchmark"
          />
          <SegmentedControl
            size="sm"
            aria-label="Archivage"
            value={archived ? "archived" : "active"}
            onValueChange={(v) => set({ archived: v === "archived" ? "true" : null, page: null })}
            options={[
              { value: "active", label: "Actifs" },
              { value: "archived", label: "Archivés" },
            ]}
          />
        </div>
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} variant="plain" />
        ) : query.isPending ? (
          <TableSkeleton />
        ) : items.length === 0 && !search.applied && !archived ? (
          <EmptyState
            variant="plain"
            icon={<Layers />}
            title="Aucun benchmark"
            description="Un benchmark compare plusieurs versions d'agents sur un même jeu de scénarios. Incluez des scénarios privés et fresh pour mesurer le sur-apprentissage."
            action={
              <RequireRole min="editor">
                <Button size="sm" leftIcon={<Plus aria-hidden />} onClick={() => setCreateOpen(true)}>
                  Créer un benchmark
                </Button>
              </RequireRole>
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Benchmark</TableHead>
                <TableHead className="text-right">Matrice</TableHead>
                <TableHead className="hidden md:table-cell">Dernière exécution</TableHead>
                <TableHead className="hidden lg:table-cell text-right">Exécutions</TableHead>
                <TableHead className="hidden sm:table-cell">Mis à jour</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 ? (
                <TableEmptyRow colSpan={5}>Aucun benchmark ne correspond à ces filtres.</TableEmptyRow>
              ) : (
                items.map((b) => {
                  const last = b.last_execution;
                  return (
                    <TableRow
                      key={b.id}
                      interactive
                      tabIndex={0}
                      onClick={() => router.push(`/benchmarks/${b.id}`)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") router.push(`/benchmarks/${b.id}`);
                      }}
                    >
                      <TableCell>
                        <div className="grid gap-0.5">
                          <Link
                            href={`/benchmarks/${b.id}`}
                            className="font-medium text-foreground hover:underline"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {b.name}
                          </Link>
                          <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                            <span className="font-mono">{b.slug}</span>
                            {b.tags.map((t) => (
                              <Badge key={t} variant="outline">
                                {t}
                              </Badge>
                            ))}
                            {b.archived ? <Badge tone="neutral">Archivé</Badge> : null}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        <span className="text-foreground">
                          {b.n_scenarios} × {b.n_agents} × {b.repetitions}
                        </span>
                        <span className="block text-xs text-muted-foreground">
                          {formatNumber(b.n_scenarios * b.n_agents * b.repetitions, 0)} runs
                        </span>
                      </TableCell>
                      <TableCell className="hidden md:table-cell">
                        {last ? (
                          <div className="flex items-center gap-3">
                            <span className="text-xs text-muted-foreground">n° {last.number}</span>
                            <ExecutionStatusBadge status={last.status} />
                            {isActiveExecution(last.status) ? (
                              <RunsProgress
                                className="w-40"
                                completed={last.completed_runs}
                                failed={last.failed_runs}
                                total={last.total_runs}
                                active
                              />
                            ) : (
                              <RelativeTime date={last.finished_at ?? last.created_at} className="text-xs text-muted-foreground" />
                            )}
                          </div>
                        ) : (
                          <span className="text-xs text-subtle-foreground">Jamais lancé</span>
                        )}
                      </TableCell>
                      <TableCell className="hidden lg:table-cell text-right tabular-nums">{b.n_executions}</TableCell>
                      <TableCell className="hidden sm:table-cell">
                        <RelativeTime date={b.updated_at} className="text-xs text-muted-foreground" />
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        )}
        {query.data && query.data.total > PAGE_SIZE ? (
          <div className="border-t border-border p-3">
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={query.data.total}
              onPageChange={(p) => set({ page: p > 1 ? p : null })}
              disabled={query.isFetching}
            />
          </div>
        ) : null}
      </Card>

      <BenchmarkFormDialog
        open={createOpen}
        onOpenChange={(o) => {
          setCreateOpen(o);
          if (!o && get("new")) set({ new: null });
        }}
      />
    </>
  );
}
