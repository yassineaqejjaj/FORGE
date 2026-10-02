"use client";

import * as React from "react";
import Link from "next/link";
import { ExternalLink, ShieldAlert } from "lucide-react";

import { ClassificationBanner } from "@/components/domain/classification-banner";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { DurationDisplay } from "@/components/domain/metric-display";
import { ScoreBadge } from "@/components/domain/score-badge";
import { RunStatusBadge } from "@/components/domain/status-badge";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ErrorState } from "@/components/ui/error-state";
import { Spinner } from "@/components/ui/spinner";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useRunsList, type MatrixCell, type MatrixData } from "@/lib/api/benchmarks";
import { scenarioCategoryLabel } from "@/lib/enums";
import { formatPercent, formatScore100 } from "@/lib/format";
import { scoreTone } from "@/lib/scores";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

interface CellTarget {
  cell: MatrixCell;
  scenarioName: string;
  agentLabel: string;
}

function CellRunsDialog({ executionId, target, onClose }: { executionId: string; target: CellTarget | null; onClose: () => void }) {
  const runs = useRunsList(
    {
      benchmark_execution_id: executionId,
      scenario_version_id: target?.cell.scenario_version_id,
      agent_version_id: target?.cell.agent_version_id,
      page_size: 50,
    },
    Boolean(target),
  );
  return (
    <Dialog open={Boolean(target)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>{target?.scenarioName}</DialogTitle>
          <DialogDescription>
            {target?.agentLabel} · {target?.cell.n_runs} répétition(s)
          </DialogDescription>
        </DialogHeader>
        {runs.isPending ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : runs.isError ? (
          <ErrorState error={runs.error} size="sm" />
        ) : (
          <ul className="grid gap-2">
            {runs.data.items.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-border px-3 py-2">
                <span className="text-xs text-muted-foreground">Répétition {r.repetition + 1}</span>
                <RunStatusBadge status={r.status} />
                <ScoreBadge value={r.composite_score} passed={r.passed} gateFailed={r.gate_failed} />
                {r.error_type ? <ErrorTypeBadge code={r.error_type} /> : null}
                <DurationDisplay ms={r.latency_ms} muted />
                <Button asChild size="xs" variant="secondary" className="ml-auto">
                  <Link href={`/runs/${r.id}`}>
                    Ouvrir <ExternalLink aria-hidden />
                  </Link>
                </Button>
              </li>
            ))}
            {runs.data.items.length === 0 ? <p className="text-[13px] text-muted-foreground">Aucun run visible.</p> : null}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Scenario × agent matrix coloured by mean composite; click a cell to open its runs. */
export function MatrixHeatmap({ matrix, executionId, classifications }: { matrix: MatrixData; executionId: string; classifications?: number[] }) {
  const [target, setTarget] = React.useState<CellTarget | null>(null);
  const scenarios = matrix.scenarios ?? [];
  const agents = matrix.agents ?? [];
  const cells = new Map((matrix.cells ?? []).map((c) => [`${c.scenario_version_id}|${c.agent_version_id}`, c]));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Matrice scénario × version</CardTitle>
        <CardDescription>
          Composite moyen sur les répétitions ; écart-type, taux de réussite et erreurs au survol. Cliquez une cellule pour
          ouvrir ses runs.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {classifications?.length ? <ClassificationBanner levels={classifications} context="comparison" compact /> : null}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-separate border-spacing-1 text-[13px]">
            <thead>
              <tr>
                <th scope="col" className="w-[40%] px-2 text-left text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground">
                  Scénario
                </th>
                {agents.map((a) => (
                  <th key={a.agent_version_id} scope="col" className="px-2 text-center text-[12px] font-medium text-foreground">
                    {a.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s) => (
                <tr key={s.scenario_version_id}>
                  <th scope="row" className="px-2 py-1 text-left font-normal">
                    <div className="flex items-center gap-2">
                      <VisibilityBadge visibility={s.visibility} iconOnly />
                      <div className="grid min-w-0">
                        <span className="truncate font-medium">{s.name}</span>
                        <span className="truncate text-[11px] text-muted-foreground">
                          {scenarioCategoryLabel(s.category)} · {s.difficulty}
                        </span>
                      </div>
                    </div>
                  </th>
                  {agents.map((a) => {
                    const c = cells.get(`${s.scenario_version_id}|${a.agent_version_id}`);
                    if (!c) {
                      return (
                        <td key={a.agent_version_id} className="rounded-md bg-muted/40 text-center text-subtle-foreground">
                          —
                        </td>
                      );
                    }
                    const tone = toneClasses(scoreTone(c.composite_mean));
                    return (
                      <td key={a.agent_version_id} className="p-0">
                        <SimpleTooltip
                          content={
                            <span className="grid gap-0.5">
                              <span>
                                Composite {formatScore100(c.composite_mean)} ± {formatScore100(c.composite_std)} ({c.n_scored}/{c.n_runs} runs)
                              </span>
                              <span>Réussite {formatPercent(c.pass_rate)}</span>
                              {c.gate_failures ? <span>{c.gate_failures} échec(s) de garde-fou</span> : null}
                              {c.error_types.length ? <span>Erreurs : {c.error_types.join(", ")}</span> : null}
                            </span>
                          }
                        >
                          <button
                            type="button"
                            onClick={() => setTarget({ cell: c, scenarioName: s.name, agentLabel: a.label })}
                            className={cn(
                              "flex h-12 w-full flex-col items-center justify-center rounded-md ring-1 ring-inset transition-[filter,box-shadow] hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                              tone.soft,
                            )}
                            aria-label={`${s.name} — ${a.label} : composite ${formatScore100(c.composite_mean)}`}
                          >
                            <span className="text-sm font-semibold tabular-nums">{formatScore100(c.composite_mean)}</span>
                            <span className="flex items-center gap-1 text-[10.5px] opacity-80">
                              {c.gate_failures ? <ShieldAlert className="size-3" aria-hidden /> : null}
                              {c.error_count ? `${c.error_count} err.` : formatPercent(c.pass_rate)}
                            </span>
                          </button>
                        </SimpleTooltip>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ScaleLegend />
      </CardContent>
      <CellRunsDialog executionId={executionId} target={target} onClose={() => setTarget(null)} />
    </Card>
  );
}

function ScaleLegend() {
  const bands: Array<{ label: string; v: number }> = [
    { label: "≥ 80", v: 85 },
    { label: "65–80", v: 70 },
    { label: "50–65", v: 55 },
    { label: "35–50", v: 40 },
    { label: "< 35", v: 20 },
  ];
  return (
    <ul className="flex flex-wrap items-center gap-3 text-[11.5px] text-muted-foreground" aria-label="Échelle de couleur">
      {bands.map((b) => (
        <li key={b.label} className="flex items-center gap-1.5">
          <span className={cn("size-3 rounded ring-1 ring-inset", toneClasses(scoreTone(b.v)).soft)} aria-hidden />
          {b.label}
        </li>
      ))}
    </ul>
  );
}
