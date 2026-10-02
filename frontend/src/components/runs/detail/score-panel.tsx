"use client";

import * as React from "react";
import { ChevronRight, CircleCheck, Coins, Cpu, Hash, ShieldCheck, ShieldX, Sigma, Timer, Wrench } from "lucide-react";

import { ConfidenceMeter } from "@/components/domain/confidence-meter";
import { DimensionDot, dimensionMeta } from "@/components/domain/dimension-badge";
import { DimensionRadar, type DimensionValues } from "@/components/domain/dimension-radar";
import { GateActionBadge, ScoreSourceBadge } from "@/components/domain/enum-badge";
import { CostDisplay, DurationDisplay, TokenCount } from "@/components/domain/metric-display";
import { ScoreBar } from "@/components/domain/score-bar";
import { ScoreGauge } from "@/components/domain/score-gauge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { readDimensions, readGates, readTraceSummary, type RunDetail, type RunScores, type Score } from "@/lib/api/runs";
import { DIMENSIONS, type Dimension } from "@/lib/enums";
import { formatNumber, formatPercent, formatScore, formatScore100 } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useRunDetail } from "./run-detail-context";

function CompositeCard({ scores, run }: { scores: RunScores; run: RunDetail }) {
  const composite = scores.composite;
  const passThreshold = typeof run.evaluation_config.pass_threshold === "number" ? run.evaluation_config.pass_threshold : null;
  if (!composite)
    return (
      <Card>
        <CardContent className="pt-5">
          <EmptyState
            size="sm"
            variant="plain"
            icon={<Sigma />}
            title="Pas encore de score composite"
            description={scores.status_detail ?? "Le run n'a pas encore été évalué."}
          />
        </CardContent>
      </Card>
    );
  const capped = Math.abs(composite.raw_value - composite.value) > 0.05;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>Score composite</CardTitle>
        <CardDescription>Round {composite.round} · calculé par l&apos;API à partir des dimensions disponibles</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="flex items-center gap-4">
          <ScoreGauge
            value={composite.value}
            size="lg"
            label="/ 100"
            passThreshold={passThreshold}
            passed={composite.passed}
            gateFailed={composite.gate_failed}
          />
          <dl className="grid flex-1 gap-2 text-[13px]">
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Résultat</dt>
              <dd>
                {composite.gate_failed ? (
                  <Badge tone="red" variant="solid" icon={<ShieldX aria-hidden />}>Garde-fou en échec</Badge>
                ) : composite.passed ? (
                  <Badge tone="green" icon={<CircleCheck aria-hidden />}>Réussi</Badge>
                ) : (
                  <Badge tone="amber" dot>Sous le seuil</Badge>
                )}
              </dd>
            </div>
            {passThreshold !== null ? (
              <div className="flex items-center justify-between gap-2">
                <dt className="text-muted-foreground">Seuil de réussite</dt>
                <dd className="font-medium tabular-nums">{formatScore100(passThreshold)}</dd>
              </div>
            ) : null}
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Score avant garde-fous</dt>
              <dd className={cn("font-medium tabular-nums", capped && "line-through decoration-red-500/70")}>{formatScore100(composite.raw_value)}</dd>
            </div>
            {capped ? (
              <div className="flex items-center justify-between gap-2">
                <dt className="text-muted-foreground">Après garde-fous</dt>
                <dd className="font-semibold tabular-nums text-red-700 dark:text-red-300">{formatScore100(composite.value)}</dd>
              </div>
            ) : null}
          </dl>
        </div>
        <div className="grid gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-subtle-foreground">Formule</span>
          <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 font-mono text-[11.5px] leading-relaxed text-foreground">{composite.formula}</p>
        </div>
        {composite.missing_dimensions.length ? (
          <p className="text-xs text-muted-foreground">
            Dimensions absentes (poids renormalisés) :{" "}
            {composite.missing_dimensions.map((d) => dimensionMeta(d).label).join(", ")}.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function GatesCard({ scores }: { scores: RunScores }) {
  const gates = readGates(scores.composite?.gates);
  if (!gates.length) return null;
  const failed = gates.filter((g) => !g.passed).length;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2">
          Garde-fous
          <Badge tone={failed ? "red" : "green"}>{failed ? `${failed} déclenché${failed > 1 ? "s" : ""}` : "Tous respectés"}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="grid gap-2">
          {gates.map((g) => (
            <li
              key={g.gate_id}
              className={cn(
                "flex items-start gap-2.5 rounded-lg border px-3 py-2 text-[13px]",
                g.passed ? "border-border" : "border-red-300 bg-red-50/70 dark:border-red-400/30 dark:bg-red-400/10",
              )}
            >
              {g.passed ? (
                <ShieldCheck className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-label="Respecté" />
              ) : (
                <ShieldX className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-400" aria-label="Déclenché" />
              )}
              <div className="grid min-w-0 flex-1 gap-0.5">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-mono text-xs font-medium">{g.gate_id}</span>
                  <GateActionBadge value={g.action} />
                  {!g.passed && g.action === "cap" && typeof g.cap === "number" ? (
                    <Badge tone="red" variant="outline">plafond {formatScore100(g.cap, 0)}</Badge>
                  ) : null}
                </div>
                {g.detail ? <p className="text-xs text-muted-foreground">{g.detail}</p> : null}
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function DimensionsCard({ scores }: { scores: RunScores }) {
  const dims = readDimensions(scores.composite?.dimensions);
  const [view, setView] = React.useState<"bars" | "radar">("bars");
  if (!dims.length) return null;
  const values: DimensionValues = {};
  for (const d of dims) if (typeof d.value === "number") values[d.dimension as Dimension] = d.value;
  const ordered = [...dims].sort((a, b) => DIMENSIONS.indexOf(a.dimension as Dimension) - DIMENSIONS.indexOf(b.dimension as Dimension));
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2 pb-2">
        <CardTitle>Dimensions</CardTitle>
        <SegmentedControl
          size="sm"
          value={view}
          onValueChange={setView}
          options={[
            { value: "bars", label: "Barres" },
            { value: "radar", label: "Radar" },
          ]}
          aria-label="Vue des dimensions"
        />
      </CardHeader>
      <CardContent>
        {view === "radar" ? (
          <DimensionRadar values={values} label="Ce run" height={260} />
        ) : (
          <ul className="grid gap-2.5">
            {ordered.map((d) => {
              const meta = dimensionMeta(d.dimension);
              return (
                <li key={d.dimension} className="grid gap-1">
                  <div className="flex items-center justify-between gap-2 text-[13px]">
                    <span className="flex items-center gap-1.5 font-medium">
                      <DimensionDot dimension={d.dimension} />
                      {meta.label}
                    </span>
                    <SimpleTooltip
                      content={`Poids configuré ${formatPercent(d.weight ?? 0)} · poids effectif ${formatPercent(d.effective_weight ?? d.weight ?? 0, 1)} (après renormalisation)`}
                    >
                      <span className="text-[11px] tabular-nums text-muted-foreground">poids {formatPercent(d.effective_weight ?? d.weight ?? 0, 1)}</span>
                    </SimpleTooltip>
                  </div>
                  <ScoreBar value={d.value} widthClassName="flex-1" className="w-full" size="md" />
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function CriterionRow({ primary, others }: { primary: Score; others: Score[] }) {
  const ctx = useRunDetail();
  const disagreement = typeof primary.spread === "number" && primary.spread > 0;
  return (
    <li>
      <button
        type="button"
        onClick={() => ctx?.openProvenance(primary.criterion_key)}
        className="group grid w-full gap-1 rounded-lg px-2 py-1.5 text-left hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={`${primary.criterion_name ?? primary.criterion_key} : ${formatScore(primary.value)}. Voir la provenance du score`}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground">{primary.criterion_name ?? primary.criterion_key}</span>
          <ScoreSourceBadge value={primary.source} withTooltip={false} />
          <ChevronRight className="size-3.5 shrink-0 text-subtle-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" aria-hidden />
        </span>
        <ScoreBar value={primary.value} widthClassName="flex-1" className="w-full" />
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          <span className="font-mono">{primary.criterion_key}</span>
          <span>poids {formatNumber(primary.weight, 2)}</span>
          <ConfidenceMeter value={primary.confidence} className="text-[11px]" />
          {primary.n_evaluations > 1 ? <span>{primary.n_evaluations} verdicts</span> : null}
          {disagreement ? (
            <Badge tone={primary.spread! >= 0.3 ? "red" : "amber"} variant="outline">
              désaccord {formatScore(primary.spread)}
            </Badge>
          ) : null}
          {!primary.used_in_composite ? <Badge tone="neutral" variant="outline">hors composite</Badge> : null}
        </span>
        {others.map((o) => (
          <span key={o.id} className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <ScoreSourceBadge value={o.source} withTooltip={false} />
            <span className="font-medium tabular-nums text-foreground">{formatScore(o.value)}</span>
            {o.used_in_composite ? <span>retenu dans le composite</span> : <span>non retenu dans le composite</span>}
          </span>
        ))}
      </button>
    </li>
  );
}

function CriteriaCard({ scores }: { scores: RunScores }) {
  if (!scores.scores.length) return null;
  const byKey = new Map<string, Score[]>();
  for (const s of scores.scores) byKey.set(s.criterion_key, [...(byKey.get(s.criterion_key) ?? []), s]);
  const byDimension = new Map<string, Array<{ primary: Score; others: Score[] }>>();
  for (const list of byKey.values()) {
    const primary = list.find((s) => s.used_in_composite) ?? list[0]!;
    const entry = { primary, others: list.filter((s) => s !== primary) };
    byDimension.set(primary.dimension, [...(byDimension.get(primary.dimension) ?? []), entry]);
  }
  const dims = [...byDimension.keys()].sort((a, b) => DIMENSIONS.indexOf(a as Dimension) - DIMENSIONS.indexOf(b as Dimension));
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>Critères</CardTitle>
        <CardDescription>Cliquez sur un critère pour voir la provenance complète de son score.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {dims.map((d) => (
          <section key={d} className="grid gap-1" aria-label={dimensionMeta(d).label}>
            <h4 className="flex items-center gap-1.5 px-2 text-[11px] font-semibold uppercase tracking-wide text-subtle-foreground">
              <DimensionDot dimension={d} />
              {dimensionMeta(d).label}
            </h4>
            <ul className="grid">
              {byDimension.get(d)!.map((entry) => (
                <CriterionRow key={entry.primary.criterion_key} primary={entry.primary} others={entry.others} />
              ))}
            </ul>
          </section>
        ))}
      </CardContent>
    </Card>
  );
}

function ResourcesCard({ run }: { run: RunDetail }) {
  const trace = readTraceSummary(run.trace);
  if (!trace) return null;
  const rows: Array<{ icon: React.ReactNode; label: string; value: React.ReactNode }> = [
    { icon: <Coins aria-hidden />, label: "Coût estimé", value: <CostDisplay value={trace.cost} /> },
    { icon: <Timer aria-hidden />, label: "Latence", value: <DurationDisplay ms={trace.latency_ms} /> },
    { icon: <Hash aria-hidden />, label: "Tokens", value: <TokenCount total={trace.total_tokens} input={trace.input_tokens} output={trace.output_tokens} /> },
    { icon: <Cpu aria-hidden />, label: "Appels modèle", value: formatNumber(trace.model_calls ?? 0, 0) },
    { icon: <Wrench aria-hidden />, label: "Appels d'outils", value: formatNumber(trace.tool_calls ?? 0, 0) },
  ];
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>Ressources</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-3">
          {rows.map((r) => (
            <div key={r.label} className="grid gap-0.5">
              <dt className="flex items-center gap-1.5 text-[11px] text-muted-foreground [&_svg]:size-3">
                {r.icon}
                {r.label}
              </dt>
              <dd className="text-sm font-medium tabular-nums">{r.value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

/** Right column: composite + formula, gates, dimensions (bars / radar), criteria by dimension, resources. */
export function ScorePanel({ run, scores }: { run: RunDetail; scores: RunScores }) {
  return (
    <div className="grid gap-4">
      <CompositeCard scores={scores} run={run} />
      <GatesCard scores={scores} />
      <DimensionsCard scores={scores} />
      <CriteriaCard scores={scores} />
      <ResourcesCard run={run} />
    </div>
  );
}
