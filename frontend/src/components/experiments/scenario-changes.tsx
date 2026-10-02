"use client";

import * as React from "react";
import Link from "next/link";
import { Columns2, ExternalLink, TrendingDown, TrendingUp } from "lucide-react";

import { useRunsList } from "@/lib/api/benchmarks";
import type { ScenarioChange } from "@/lib/api/experiments";
import { DeltaIndicator } from "@/components/domain/delta-indicator";
import { RegressionSeverityBadge } from "@/components/domain/enum-badge";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { CostDisplay, DurationDisplay } from "@/components/domain/metric-display";
import { ScoreBadge } from "@/components/domain/score-badge";
import { RunStatusBadge } from "@/components/domain/status-badge";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { scenarioCategoryLabel } from "@/lib/enums";
import { formatNumber, formatScore100 } from "@/lib/format";

function ArmRuns({ experimentId, change, arm, label }: { experimentId: string; change: ScenarioChange; arm: "baseline" | "candidate"; label: string }) {
  const runs = useRunsList({ experiment_id: experimentId, scenario_version_id: change.scenario_version_id, arm, page_size: 50 });
  return (
    <div className="grid content-start gap-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[13px] font-semibold">{label}</p>
        <span className="text-xs tabular-nums text-muted-foreground">
          moyenne {formatScore100(arm === "baseline" ? change.baseline_mean : change.candidate_mean)}
        </span>
      </div>
      {runs.isPending ? (
        <div className="flex justify-center py-6">
          <Spinner />
        </div>
      ) : runs.isError ? (
        <ErrorState error={runs.error} size="sm" />
      ) : runs.data.items.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">Aucun run.</p>
      ) : (
        <ul className="grid gap-2">
          {runs.data.items.map((r) => (
            <li key={r.id} className="grid gap-1.5 rounded-lg border border-border p-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">Rép. {r.repetition + 1}</span>
                <RunStatusBadge status={r.status} />
                <ScoreBadge value={r.composite_score} passed={r.passed} gateFailed={r.gate_failed} />
                <Button asChild variant="ghost" size="xs" className="ml-auto">
                  <Link href={`/runs/${r.id}`}>
                    Ouvrir <ExternalLink aria-hidden />
                  </Link>
                </Button>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                <DurationDisplay ms={r.latency_ms} muted />
                <CostDisplay value={r.cost} muted />
                {r.error_type ? <ErrorTypeBadge code={r.error_type} /> : null}
                {r.gate_failed ? <Badge tone="red">Garde-fou en échec</Badge> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Side-by-side baseline / candidate runs of one scenario version. */
export function ScenarioRunsSheet({
  experimentId,
  change,
  onClose,
  baselineLabel,
  candidateLabel,
}: {
  experimentId: string;
  change: ScenarioChange | null;
  onClose: () => void;
  baselineLabel: string;
  candidateLabel: string;
}) {
  return (
    <Sheet open={Boolean(change)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent size="xl">
        {change ? (
          <>
            <SheetHeader>
              <SheetTitle>{change.name}</SheetTitle>
              <SheetDescription>
                {formatScore100(change.baseline_mean)} → {formatScore100(change.candidate_mean)} (
                {change.delta !== null && change.delta !== undefined ? `${change.delta > 0 ? "+" : ""}${formatNumber(change.delta, 1)} pts` : "—"}
                ) · seuil de bruit −{formatNumber(change.threshold, 1)} pts
              </SheetDescription>
            </SheetHeader>
            <SheetBody>
              {change.reasons?.length ? (
                <ul className="mb-4 grid gap-1 text-[13px] text-muted-foreground">
                  {(change.reasons ?? []).map((r) => (
                    <li key={r}>• {r}</li>
                  ))}
                </ul>
              ) : null}
              <div className="grid gap-4 md:grid-cols-2">
                <ArmRuns experimentId={experimentId} change={change} arm="baseline" label={`Baseline · ${baselineLabel}`} />
                <ArmRuns experimentId={experimentId} change={change} arm="candidate" label={`Candidate · ${candidateLabel}`} />
              </div>
            </SheetBody>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function ChangesTable({
  rows,
  onOpen,
  showSeverity,
  emptyLabel,
}: {
  rows: ScenarioChange[];
  onOpen: (c: ScenarioChange) => void;
  showSeverity?: boolean;
  emptyLabel: string;
}) {
  return (
    <Table dense>
      <TableHeader>
        <TableRow>
          <TableHead>Scénario</TableHead>
          <TableHead className="text-right">Baseline → candidate</TableHead>
          <TableHead className="text-right">Δ</TableHead>
          {showSeverity ? <TableHead>Gravité</TableHead> : null}
          <TableHead>Raisons</TableHead>
          <TableHead className="w-28 text-right">
            <span className="sr-only">Runs</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.length === 0 ? (
          <TableEmptyRow colSpan={showSeverity ? 6 : 5}>{emptyLabel}</TableEmptyRow>
        ) : (
          rows.map((c) => (
            <TableRow key={c.scenario_version_id}>
              <TableCell>
                <div className="flex items-center gap-2">
                  <VisibilityBadge visibility={c.visibility} iconOnly />
                  <div className="grid min-w-0">
                    <span className="truncate font-medium">{c.name}</span>
                    <span className="text-[11px] text-muted-foreground">
                      {scenarioCategoryLabel(c.category)} · {c.difficulty} · {c.n_baseline}+{c.n_candidate} runs
                    </span>
                  </div>
                </div>
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatScore100(c.baseline_mean)} → <span className="font-medium">{formatScore100(c.candidate_mean)}</span>
              </TableCell>
              <TableCell className="text-right">
                <DeltaIndicator value={c.delta} unit="pts" />
              </TableCell>
              {showSeverity ? (
                <TableCell>{c.severity ? <RegressionSeverityBadge value={c.severity} /> : "—"}</TableCell>
              ) : null}
              <TableCell>
                <div className="grid max-w-md gap-1 text-[12.5px] text-muted-foreground">
                  {(c.reasons ?? []).slice(0, 2).map((r) => (
                    <span key={r}>{r}</span>
                  ))}
                  {c.new_critical_errors?.length || (c.candidate_gate_failures ?? 0) > (c.baseline_gate_failures ?? 0) ? (
                    <span className="flex flex-wrap gap-1">
                      {(c.candidate_gate_failures ?? 0) > (c.baseline_gate_failures ?? 0) ? (
                        <Badge tone="red">
                          Garde-fou : {c.baseline_gate_failures} → {c.candidate_gate_failures}
                        </Badge>
                      ) : null}
                      {(c.new_critical_errors ?? []).map((e) => (
                        <ErrorTypeBadge key={e} code={e} />
                      ))}
                    </span>
                  ) : null}
                  {c.resolved_critical_errors?.length ? (
                    <span className="flex flex-wrap items-center gap-1">
                      Résolues : {(c.resolved_critical_errors ?? []).map((e) => <ErrorTypeBadge key={e} code={e} />)}
                    </span>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="text-right">
                <Button variant="secondary" size="xs" leftIcon={<Columns2 aria-hidden />} onClick={() => onOpen(c)}>
                  Comparer
                </Button>
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}

const STATUS_LABEL: Record<string, string> = {
  regression: "Régression",
  improvement: "Amélioration",
  stable: "Stable",
  unpaired: "Non apparié",
};

/** Regressions, improvements and every paired scenario. */
export function ScenarioChangesSection({
  experimentId,
  regressions,
  improvements,
  scenarios,
  baselineLabel,
  candidateLabel,
}: {
  experimentId: string;
  regressions: ScenarioChange[];
  improvements: ScenarioChange[];
  scenarios: ScenarioChange[];
  baselineLabel: string;
  candidateLabel: string;
}) {
  const [open, setOpen] = React.useState<ScenarioChange | null>(null);
  const [view, setView] = React.useState<"all" | "stable" | "unpaired">("all");
  const others = scenarios.filter((s) => (view === "all" ? true : s.status === view));
  const severityRank: Record<string, number> = { critical: 0, major: 1, minor: 2 };
  const sortedRegressions = [...regressions].sort(
    (a, b) => (severityRank[a.severity ?? "minor"] ?? 3) - (severityRank[b.severity ?? "minor"] ?? 3) || (a.delta ?? 0) - (b.delta ?? 0),
  );

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingDown className="size-4 text-red-600" aria-hidden />
            Régressions ({regressions.length})
          </CardTitle>
          <CardDescription>
            Δ ≤ −max(5, 2σ bruit) ; critique si nouveau garde-fou en échec, nouvelle erreur critique ou Δ ≤ −15 ; majeure si
            Δ ≤ −10.
          </CardDescription>
        </CardHeader>
        {regressions.length === 0 ? (
          <EmptyState
            variant="plain"
            size="sm"
            icon={<TrendingDown />}
            title="Aucune régression"
            description="Aucun scénario ne se dégrade au-delà du bruit mesuré."
          />
        ) : (
          <ChangesTable rows={sortedRegressions} onOpen={setOpen} showSeverity emptyLabel="" />
        )}
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="size-4 text-emerald-600" aria-hidden />
            Améliorations ({improvements.length})
          </CardTitle>
          <CardDescription>Scénarios qui progressent au-delà du bruit mesuré.</CardDescription>
        </CardHeader>
        <ChangesTable
          rows={[...improvements].sort((a, b) => (b.delta ?? 0) - (a.delta ?? 0))}
          onOpen={setOpen}
          emptyLabel="Aucune amélioration au-delà du bruit."
        />
      </Card>
      <Card>
        <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
          <div className="grid gap-1">
            <CardTitle>Tous les scénarios ({scenarios.length})</CardTitle>
            <CardDescription>Comparaison appariée par version de scénario.</CardDescription>
          </div>
          <SegmentedControl
            size="sm"
            aria-label="Filtrer les scénarios"
            value={view}
            onValueChange={setView}
            options={[
              { value: "all", label: "Tous" },
              { value: "stable", label: "Stables" },
              { value: "unpaired", label: "Non appariés" },
            ]}
          />
        </CardHeader>
        <Table dense>
          <TableHeader>
            <TableRow>
              <TableHead>Scénario</TableHead>
              <TableHead>Statut</TableHead>
              <TableHead className="text-right">Baseline → candidate</TableHead>
              <TableHead className="text-right">Δ</TableHead>
              <TableHead className="text-right">Bruit σ</TableHead>
              <TableHead className="w-28 text-right">
                <span className="sr-only">Runs</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {others.length === 0 ? (
              <TableEmptyRow colSpan={6}>Aucun scénario.</TableEmptyRow>
            ) : (
              others.map((c) => (
                <TableRow key={c.scenario_version_id}>
                  <TableCell>
                    <span className="flex items-center gap-2">
                      <VisibilityBadge visibility={c.visibility} iconOnly />
                      <span className="truncate">{c.name}</span>
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge
                      tone={c.status === "regression" ? "red" : c.status === "improvement" ? "green" : c.status === "unpaired" ? "amber" : "neutral"}
                    >
                      {STATUS_LABEL[c.status] ?? c.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatScore100(c.baseline_mean)} → {formatScore100(c.candidate_mean)}
                  </TableCell>
                  <TableCell className="text-right">
                    <DeltaIndicator value={c.delta} unit="pts" />
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {formatNumber(c.noise_std, 1)}
                    {c.noise_estimated ? "" : " (défaut)"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="xs" leftIcon={<Columns2 aria-hidden />} onClick={() => setOpen(c)}>
                      Runs
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>
      <ScenarioRunsSheet
        experimentId={experimentId}
        change={open}
        onClose={() => setOpen(null)}
        baselineLabel={baselineLabel}
        candidateLabel={candidateLabel}
      />
    </div>
  );
}
