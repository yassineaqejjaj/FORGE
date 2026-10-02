"use client";

import * as React from "react";
import Link from "next/link";
import { Ban, ListChecks, Play } from "lucide-react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { RelativeTime } from "@/components/domain/relative-time";
import { ExecutionStatusBadge } from "@/components/domain/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Pagination } from "@/components/ui/pagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { isActiveExecution, useBenchmarkExecutions, useCancelExecution, type Execution } from "@/lib/api/benchmarks";
import { formatDateTime, formatMs } from "@/lib/format";
import { RunsProgress, TableSkeleton } from "./common";

const PAGE_SIZE = 10;

function durationOf(e: Execution): string | null {
  if (!e.started_at) return null;
  const end = e.finished_at ? new Date(e.finished_at).getTime() : null;
  if (!end) return null;
  return formatMs(end - new Date(e.started_at).getTime());
}

export interface ExecutionsCardProps {
  benchmarkId: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onLaunch?: () => void;
}

/** Executions of a benchmark (newest first) with live progress bars and cancel. */
export function ExecutionsCard({ benchmarkId, selectedId, onSelect, onLaunch }: ExecutionsCardProps) {
  const [page, setPage] = React.useState(1);
  const query = useBenchmarkExecutions(benchmarkId, { page, page_size: PAGE_SIZE });
  const cancel = useCancelExecution();
  const [toCancel, setToCancel] = React.useState<Execution | null>(null);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ListChecks className="size-4 text-muted-foreground" aria-hidden />
          Exécutions
        </CardTitle>
        <CardDescription>Chaque lancement fige la matrice (versions de scénarios et d&apos;agents).</CardDescription>
      </CardHeader>
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} variant="plain" size="sm" />
      ) : query.isPending ? (
        <TableSkeleton rows={3} />
      ) : query.data.items.length === 0 ? (
        <EmptyState
          variant="plain"
          size="sm"
          icon={<Play />}
          title="Jamais lancé"
          description="Lancez le benchmark pour obtenir un classement."
          action={
            onLaunch ? (
              <RequireRole min="editor">
                <Button size="sm" onClick={onLaunch} leftIcon={<Play aria-hidden />}>
                  Lancer
                </Button>
              </RequireRole>
            ) : undefined
          }
        />
      ) : (
        <Table dense>
          <TableHeader>
            <TableRow>
              <TableHead>N°</TableHead>
              <TableHead>Statut</TableHead>
              <TableHead>Progression</TableHead>
              <TableHead className="hidden md:table-cell">Lancée</TableHead>
              <TableHead className="w-24 text-right">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data.items.map((e) => {
              const active = isActiveExecution(e.status);
              const selected = e.id === selectedId;
              return (
                <TableRow
                  key={e.id}
                  interactive
                  selected={selected}
                  tabIndex={0}
                  aria-selected={selected}
                  onClick={() => onSelect(e.id)}
                  onKeyDown={(ev) => {
                    if (ev.key === "Enter") onSelect(e.id);
                  }}
                >
                  <TableCell className="font-medium tabular-nums">
                    n° {e.number}
                    {selected ? (
                      <Badge tone="orange" className="ml-2">
                        Affichée
                      </Badge>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <ExecutionStatusBadge status={e.status} detail={e.error} />
                  </TableCell>
                  <TableCell>
                    <RunsProgress className="w-44" completed={e.completed_runs} failed={e.failed_runs} total={e.total_runs} active={active} />
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    <span className="grid text-xs">
                      <span title={formatDateTime(e.created_at)}>
                        <RelativeTime date={e.created_at} />
                      </span>
                      <span className="text-muted-foreground">
                        {e.trigger}
                        {durationOf(e) ? ` · ${durationOf(e)}` : ""}
                      </span>
                    </span>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1" onClick={(ev) => ev.stopPropagation()}>
                      <Button asChild variant="ghost" size="xs">
                        <Link href={`/runs?benchmark_execution_id=${e.id}`}>Runs</Link>
                      </Button>
                      {active ? (
                        <RequireRole min="editor">
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            aria-label={`Annuler l'exécution n° ${e.number}`}
                            onClick={() => setToCancel(e)}
                          >
                            <Ban aria-hidden />
                          </Button>
                        </RequireRole>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
      {query.data && query.data.total > PAGE_SIZE ? (
        <div className="border-t border-border p-3">
          <Pagination compact page={page} pageSize={PAGE_SIZE} total={query.data.total} onPageChange={setPage} />
        </div>
      ) : null}
      <ConfirmDialog
        open={Boolean(toCancel)}
        onOpenChange={(o) => !o && setToCancel(null)}
        title={`Annuler l'exécution n° ${toCancel?.number ?? ""} ?`}
        description="Les runs en attente ou en cours sont annulés ; les résultats déjà obtenus sont agrégés."
        confirmLabel="Annuler l'exécution"
        cancelLabel="Continuer"
        destructive
        onConfirm={async () => {
          if (!toCancel) return;
          try {
            const res = await cancel.mutateAsync(toCancel.id);
            toast.success(`${res.detail} (${res.cancelled_runs} run(s) annulé(s))`);
            setToCancel(null);
          } catch {
            // error toast shown by the mutation cache
          }
        }}
      />
    </Card>
  );
}
