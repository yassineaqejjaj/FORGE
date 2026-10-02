"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, Eye, Minus } from "lucide-react";

import { DeltaIndicator } from "@/components/domain/delta-indicator";
import { ScoreBadge } from "@/components/domain/score-badge";
import { RunPicker } from "@/components/judges/run-picker";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useBenchmarkExecutions, useBenchmarks } from "@/lib/api/benchmarks";
import { errorMessage } from "@/lib/api/client";
import { usePreviewEvaluationConfig, type ConfigBehaviourInput, type PreviewItem, type PreviewResult } from "@/lib/api/evaluation-configs";
import { formatPercent, formatScore100 } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Positions (1 = best) of the items sorted by a value; ordering only, values come from the API. */
function positions(items: PreviewItem[], pick: (i: PreviewItem) => number | null | undefined): Map<string, number> {
  const sorted = [...items].sort((a, b) => (pick(b) ?? -1) - (pick(a) ?? -1));
  return new Map(sorted.map((it, idx) => [it.run_id, idx + 1]));
}

function PassCell({ passed, gate }: { passed: boolean | null | undefined; gate: boolean }) {
  if (gate) return <Badge tone="red">Garde-fou</Badge>;
  if (passed === null || passed === undefined) return <span className="text-subtle-foreground">—</span>;
  return passed ? <Badge tone="green">Réussi</Badge> : <Badge tone="neutral">Échoué</Badge>;
}

function PreviewResults({ result }: { result: PreviewResult }) {
  const before = positions(result.items, (i) => i.before);
  const after = positions(result.items, (i) => i.after);
  const items = [...result.items].sort((a, b) => Math.abs(b.delta ?? 0) - Math.abs(a.delta ?? 0));
  const changedPass = result.items.filter((i) => i.passed_before !== i.passed_after).length;
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border p-3">
          <p className="text-[12px] text-muted-foreground">Composite moyen</p>
          <p className="flex items-baseline gap-2 tabular-nums">
            <span className="text-muted-foreground">{formatScore100(result.mean_before)}</span>→
            <span className="text-lg font-semibold">{formatScore100(result.mean_after)}</span>
            <DeltaIndicator
              value={typeof result.mean_after === "number" && typeof result.mean_before === "number" ? result.mean_after - result.mean_before : null}
              unit="pts"
            />
          </p>
        </div>
        <div className="rounded-lg border border-border p-3">
          <p className="text-[12px] text-muted-foreground">Taux de réussite</p>
          <p className="flex items-baseline gap-2 tabular-nums">
            <span className="text-muted-foreground">{formatPercent(result.pass_rate_before)}</span>→
            <span className="text-lg font-semibold">{formatPercent(result.pass_rate_after)}</span>
          </p>
        </div>
        <div className="rounded-lg border border-border p-3">
          <p className="text-[12px] text-muted-foreground">Runs recalculés</p>
          <p className="text-lg font-semibold tabular-nums">
            {result.items.length}
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {changedPass} changement(s) de réussite · {result.skipped.length} ignoré(s)
            </span>
          </p>
        </div>
      </div>
      {result.notes?.length ? (
        <Alert tone="sky">
          <ul>
            {(result.notes ?? []).map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Alert>
      ) : null}
      {result.skipped.length ? (
        <details className="text-[13px]">
          <summary className="cursor-pointer text-muted-foreground">{result.skipped.length} run(s) ignoré(s)</summary>
          <ul className="mt-1 grid gap-0.5 text-xs text-muted-foreground">
            {result.skipped.map((s, i) => (
              <li key={i}>{Object.values(s).join(" — ")}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <Table dense containerClassName="max-h-[32rem] rounded-lg border border-border">
        <TableHeader>
          <TableRow>
            <TableHead>Run</TableHead>
            <TableHead className="text-right">Avant</TableHead>
            <TableHead className="text-right">Après</TableHead>
            <TableHead className="text-right">Δ</TableHead>
            <TableHead>Réussite avant → après</TableHead>
            <TableHead className="text-right">Rang</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((i) => {
            const rb = before.get(i.run_id) ?? 0;
            const ra = after.get(i.run_id) ?? 0;
            const move = rb - ra;
            return (
              <TableRow key={i.run_id}>
                <TableCell>
                  <SimpleTooltip content={i.formula} className="max-w-md">
                    <Link href={`/runs/${i.run_id}`} className="grid hover:underline">
                      <span className="truncate font-medium">{i.scenario_name}</span>
                      <span className="truncate text-[11px] text-muted-foreground">{i.agent_label}</span>
                    </Link>
                  </SimpleTooltip>
                </TableCell>
                <TableCell className="text-right">
                  <ScoreBadge value={i.before} gateFailed={i.gate_failed_before} passed={i.passed_before} />
                </TableCell>
                <TableCell className="text-right">
                  <ScoreBadge value={i.after} gateFailed={i.gate_failed_after} passed={i.passed_after} />
                </TableCell>
                <TableCell className="text-right">
                  <DeltaIndicator value={i.delta} />
                </TableCell>
                <TableCell>
                  <span className="flex items-center gap-1">
                    <PassCell passed={i.passed_before} gate={i.gate_failed_before} />
                    <span className="text-subtle-foreground">→</span>
                    <PassCell passed={i.passed_after} gate={i.gate_failed_after} />
                  </span>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  <span className="inline-flex items-center gap-1">
                    {rb} → {ra}
                    {move > 0 ? (
                      <ArrowUp className="size-3.5 text-emerald-600" aria-label={`gagne ${move} place(s)`} />
                    ) : move < 0 ? (
                      <ArrowDown className="size-3.5 text-red-600" aria-label={`perd ${-move} place(s)`} />
                    ) : (
                      <Minus className="size-3.5 text-subtle-foreground" aria-label="inchangé" />
                    )}
                  </span>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function ExecutionPicker({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
  const benchmarks = useBenchmarks({ page_size: 200 });
  const [benchmarkId, setBenchmarkId] = React.useState<string | undefined>();
  const executions = useBenchmarkExecutions(benchmarkId, { page_size: 50 });
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Field id="preview-benchmark" label="Benchmark">
        <SimpleSelect
          id="preview-benchmark"
          placeholder={benchmarks.isPending ? "Chargement…" : "Choisir un benchmark…"}
          value={benchmarkId}
          onValueChange={(v) => {
            setBenchmarkId(v);
            onChange(null);
          }}
          options={(benchmarks.data?.items ?? []).map((b) => ({ value: b.id, label: b.name, description: b.slug }))}
        />
      </Field>
      <Field id="preview-execution" label="Exécution">
        <SimpleSelect
          id="preview-execution"
          disabled={!benchmarkId}
          placeholder="Choisir une exécution…"
          value={value ?? undefined}
          onValueChange={onChange}
          options={(executions.data?.items ?? []).map((e) => ({
            value: e.id,
            label: `n° ${e.number}`,
            description: `${e.status} · ${e.completed_runs + e.failed_runs}/${e.total_runs} runs`,
          }))}
        />
      </Field>
    </div>
  );
}

export interface PreviewPanelProps {
  /** Configuration whose stored version (or `overrides`) is previewed. */
  configId: string;
  /** Unsaved changes to preview (editor). */
  overrides?: ConfigBehaviourInput;
  title?: string;
  description?: string;
  className?: string;
}

/** `POST /evaluation-configs/{id}/preview` on a benchmark execution or a set of runs: before / after composites. */
export function PreviewPanel({ configId, overrides, title = "Aperçu sur des runs existants", description, className }: PreviewPanelProps) {
  const preview = usePreviewEvaluationConfig(configId);
  const [source, setSource] = React.useState<"execution" | "runs">("execution");
  const [executionId, setExecutionId] = React.useState<string | null>(null);
  const [runIds, setRunIds] = React.useState<string[]>([]);
  const ready = source === "execution" ? Boolean(executionId) : runIds.length > 0;

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Eye className="size-4 text-muted-foreground" aria-hidden />
          {title}
        </CardTitle>
        <CardDescription>
          {description ??
            "Recalcule les composites avec cette configuration à partir des verdicts enregistrés (sans appel aux juges, rien n'est enregistré)."}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <SegmentedControl
          aria-label="Source de l'aperçu"
          value={source}
          onValueChange={setSource}
          options={[
            { value: "execution", label: "Exécution de benchmark" },
            { value: "runs", label: "Runs choisis" },
          ]}
        />
        {source === "execution" ? (
          <ExecutionPicker value={executionId} onChange={setExecutionId} />
        ) : (
          <RunPicker mode="multiple" value={runIds} onChange={(ids) => setRunIds(ids)} />
        )}
        <div>
          <Button
            leftIcon={<Eye aria-hidden />}
            disabled={!ready}
            loading={preview.isPending}
            onClick={() =>
              preview.mutate({
                benchmark_execution_id: source === "execution" ? executionId : undefined,
                run_ids: source === "runs" ? runIds : undefined,
                overrides: overrides ?? undefined,
              })
            }
          >
            Prévisualiser
          </Button>
        </div>
        {preview.isError ? <Alert tone="red">{errorMessage(preview.error)}</Alert> : null}
        {preview.data ? (
          <div className={cn(preview.isPending && "opacity-60")}>
            <PreviewResults result={preview.data} />
          </div>
        ) : null}
        {preview.data && overrides ? (
          <p className="text-[11.5px] text-subtle-foreground">
            Aperçu calculé avec les modifications non enregistrées du formulaire.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
