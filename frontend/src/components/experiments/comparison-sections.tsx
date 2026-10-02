"use client";

import * as React from "react";
import { CheckCircle2, Coins, Gauge, Hash, ShieldAlert, Timer, TriangleAlert } from "lucide-react";

import { DeltaIndicator, type DeltaKind } from "@/components/domain/delta-indicator";
import { DimensionBadge } from "@/components/domain/dimension-badge";
import { DimensionRadar, type DimensionValues } from "@/components/domain/dimension-radar";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { CostDisplay, DurationDisplay } from "@/components/domain/metric-display";
import { SeverityBadge } from "@/components/domain/severity-badge";
import { RecommendationBadge, VerdictBadge } from "@/components/domain/verdict-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimpleTooltip } from "@/components/ui/tooltip";
import type { ArmSummary, Comparison, MetricComparison, ResourceComparison } from "@/lib/api/experiments";
import { DIMENSIONS, isEnumValue, type Dimension } from "@/lib/enums";
import {
  formatInterval,
  formatNumber,
  formatPercent,
  formatPValue,
  formatScore100,
  formatSigned,
  formatSignedPercent,
  formatTokens,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import { ForestPlot } from "./forest-plot";

const CONFIDENCE_TONE: Record<string, "green" | "amber" | "neutral"> = { high: "green", medium: "amber", low: "neutral" };

/** Headline: recommendation, summary sentence, confidence, composite delta. */
export function RecommendationHero({ comparison }: { comparison: Comparison }) {
  const rec = comparison.recommendation;
  const c = comparison.composite;
  return (
    <Card className="overflow-hidden">
      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="grid content-start gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <RecommendationBadge recommendation={rec.recommendation} emphasis size="md" />
            <Badge tone={CONFIDENCE_TONE[rec.confidence] ?? "neutral"} variant="outline" size="md">
              Confiance {rec.confidence_label}
            </Badge>
            {comparison.provisional ? (
              <Badge tone="sky" pulse size="md">
                Calcul provisoire
              </Badge>
            ) : null}
          </div>
          <p className="max-w-3xl text-[15px] leading-relaxed text-foreground text-balance">{rec.summary}</p>
          {rec.reasons.length ? (
            <ul className="grid gap-1 text-[13px] text-muted-foreground">
              {rec.reasons.map((r) => (
                <li key={r} className="flex gap-2">
                  <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-border-strong" aria-hidden />
                  {r}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <div className="grid content-start gap-3 rounded-xl border border-border bg-muted/30 p-4 lg:min-w-64">
          <p className="text-[11.5px] font-medium uppercase tracking-wide text-subtle-foreground">Score composite</p>
          <div className="flex items-baseline gap-3 tabular-nums">
            <span className="text-lg text-muted-foreground">{formatScore100(c.baseline_mean)}</span>
            <span className="text-subtle-foreground" aria-hidden>
              →
            </span>
            <span className="text-2xl font-semibold text-foreground">{formatScore100(c.candidate_mean)}</span>
          </div>
          <DeltaIndicator value={c.delta} unit="pts" size="md" />
          <dl className="grid grid-cols-2 gap-2 text-[12.5px]">
            <div>
              <dt className="text-muted-foreground">IC 95 %</dt>
              <dd className="tabular-nums">{formatInterval(c.ci_low, c.ci_high)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Wilcoxon</dt>
              <dd className="tabular-nums">{formatPValue(c.p_value)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">P(amélioration)</dt>
              <dd className="tabular-nums">{formatPercent(c.prob_improvement)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Paires</dt>
              <dd className="tabular-nums">
                {c.n_pairs}
                {comparison.n_unpaired ? <span className="text-muted-foreground"> (+{comparison.n_unpaired} non appariés)</span> : null}
              </dd>
            </div>
          </dl>
          <VerdictBadge verdict={c.verdict} size="md" />
        </div>
      </div>
      {comparison.warnings.length ? (
        <div className="border-t border-border px-5 py-3">
          <Alert tone="amber" title="Avertissements">
            <ul className="grid gap-0.5">
              {comparison.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </Alert>
        </div>
      ) : null}
    </Card>
  );
}

/** Composite + dimension comparison table with forest plot. */
export function DimensionComparisonCard({ comparison }: { comparison: Comparison }) {
  return (
    <MetricComparisonCard
      comparison={comparison}
      title="Comparaison par dimension"
      firstColumn="Dimension"
      rows={[comparison.composite, ...comparison.dimensions]}
    />
  );
}

/** Same statistics per criterion: a version can gain on sourcing and regress on format. */
export function CriterionComparisonCard({ comparison }: { comparison: Comparison }) {
  const rows = comparison.criteria ?? [];
  if (!rows.length) return null;
  return (
    <MetricComparisonCard comparison={comparison} title="Comparaison par critère" firstColumn="Critère" rows={rows} plot={false} />
  );
}

function MetricComparisonCard({
  comparison,
  title,
  firstColumn,
  rows,
  plot = true,
}: {
  comparison: Comparison;
  title: string;
  firstColumn: string;
  rows: MetricComparison[];
  plot?: boolean;
}) {
  const stats = comparison.statistics;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>
          Moyennes en points (0–100), delta apparié par version de scénario, IC {formatPercent(stats.confidence)} par bootstrap apparié (
          {formatNumber(stats.n_resamples, 0)} rééchantillonnages), test de Wilcoxon signé. « Équivalente » : |Δ| &lt;{" "}
          {stats.equivalence_delta} pts et IC ⊂ ±{stats.equivalence_margin}.
        </CardDescription>
      </CardHeader>
      <Table dense>
        <TableHeader>
          <TableRow>
            <TableHead>{firstColumn}</TableHead>
            <TableHead className="text-right">Baseline</TableHead>
            <TableHead className="text-right">Candidate</TableHead>
            <TableHead className="text-right">Δ points</TableHead>
            <TableHead className="text-right">Δ %</TableHead>
            <TableHead className="text-right">IC 95 %</TableHead>
            <TableHead className="text-right">p</TableHead>
            <TableHead className="hidden text-right md:table-cell">P(amélioration)</TableHead>
            <TableHead>Verdict</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.key} className={cn(r.key === "composite" && "bg-muted/40 font-medium")}>
              <TableCell>
                {isEnumValue(DIMENSIONS, r.key) ? (
                  <DimensionBadge dimension={r.key} />
                ) : (
                  <span className={cn(r.key === "composite" ? "font-semibold" : "text-sm")}>
                    {r.label}
                    {r.key !== "composite" ? <span className="ml-1.5 font-mono text-[11px] text-muted-foreground">{r.key}</span> : null}
                  </span>
                )}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatScore100(r.baseline_mean)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatScore100(r.candidate_mean)}</TableCell>
              <TableCell className="text-right">
                <DeltaIndicator value={r.delta} />
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">
                {typeof r.delta_pct === "number" ? formatSigned(r.delta_pct, { unit: "%" }) : "—"}
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">{formatInterval(r.ci_low, r.ci_high)}</TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">{formatPValue(r.p_value).replace("p = ", "")}</TableCell>
              <TableCell className="hidden text-right tabular-nums text-muted-foreground md:table-cell">{formatPercent(r.prob_improvement)}</TableCell>
              <TableCell>
                <VerdictBadge verdict={r.verdict} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {plot ? (
        <CardContent className="pt-4">
          <ForestPlot rows={rows} equivalenceMargin={stats.equivalence_margin} />
        </CardContent>
      ) : null}
    </Card>
  );
}

const RESOURCE_META: Record<string, { kind: DeltaKind; icon: React.ReactNode }> = {
  cost: { kind: "cost", icon: <Coins aria-hidden /> },
  latency: { kind: "latency", icon: <Timer aria-hidden /> },
  tokens: { kind: "tokens", icon: <Hash aria-hidden /> },
};

function ResourceValue({ r, value }: { r: ResourceComparison; value: number | null | undefined }) {
  if (r.key === "cost") return <CostDisplay value={value} />;
  if (r.key === "latency") return <DurationDisplay ms={value} />;
  if (r.key === "tokens") return <span className="tabular-nums">{formatTokens(value, { compact: true })}</span>;
  return <span className="tabular-nums">{formatNumber(value)}</span>;
}

const ASSESSMENT: Record<string, { label: string; tone: "green" | "red" | "neutral" | "blue" }> = {
  gain: { label: "Gain", tone: "green" },
  loss: { label: "Perte", tone: "red" },
  stable: { label: "Stable", tone: "blue" },
  unknown: { label: "Inconnu", tone: "neutral" },
};

/** Cost / latency / tokens: lower is better (assessment computed by the API). */
export function ResourcesCard({ comparison }: { comparison: Comparison }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Coût, latence et tokens</CardTitle>
        <CardDescription>Moyennes par run ; une baisse est un gain.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-3">
        {comparison.resources.map((r) => {
          const meta = RESOURCE_META[r.key] ?? { kind: "neutral" as DeltaKind, icon: <Gauge aria-hidden /> };
          const a = ASSESSMENT[r.assessment] ?? ASSESSMENT.unknown!;
          return (
            <div key={r.key} className="grid gap-2 rounded-lg border border-border p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-[12.5px] font-medium text-muted-foreground [&_svg]:size-3.5">
                  {meta.icon}
                  {r.label}
                </span>
                <Badge tone={a.tone}>{a.label}</Badge>
              </div>
              <div className="flex flex-wrap items-baseline gap-2 text-[13px]">
                <span className="text-muted-foreground">
                  <ResourceValue r={r} value={r.baseline_mean} />
                </span>
                <span className="text-subtle-foreground" aria-hidden>
                  →
                </span>
                <span className="font-semibold">
                  <ResourceValue r={r} value={r.candidate_mean} />
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <DeltaIndicator
                  value={typeof r.relative_change === "number" ? r.relative_change * 100 : null}
                  kind={meta.kind}
                  format={() => formatSignedPercent(r.relative_change)}
                  size="md"
                />
                <span className="text-[11.5px] text-muted-foreground">{formatPValue(r.p_value)}</span>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function ArmRow({ label, arm }: { label: string; arm: ArmSummary }) {
  return (
    <TableRow>
      <TableCell>
        <div className="grid">
          <span className="text-xs text-muted-foreground">{label}</span>
          <span className="font-medium">{arm.agent_label}</span>
        </div>
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {arm.n_scored}/{arm.n_runs}
        {arm.n_failed ? <span className="block text-[11px] text-red-700 dark:text-red-400">{arm.n_failed} en échec</span> : null}
      </TableCell>
      <TableCell className="text-right tabular-nums">{formatScore100(arm.composite_mean)}</TableCell>
      <TableCell className="text-right tabular-nums">{formatPercent(arm.pass_rate)}</TableCell>
      <TableCell className="text-right tabular-nums">{formatPercent(arm.gate_failure_rate)}</TableCell>
      <TableCell className="text-right tabular-nums">{formatPercent(arm.error_rate)}</TableCell>
      <TableCell className="text-right tabular-nums">{formatPercent(arm.robustness, 1)}</TableCell>
    </TableRow>
  );
}

/** Per-arm rates + radar baseline vs candidate. */
export function ArmsCard({ comparison }: { comparison: Comparison }) {
  const base: DimensionValues = {};
  const cand: DimensionValues = {};
  for (const d of comparison.dimensions) {
    if (isEnumValue(DIMENSIONS, d.key)) {
      base[d.key as Dimension] = d.baseline_mean;
      cand[d.key as Dimension] = d.candidate_mean;
    }
  }
  if (typeof comparison.robustness.baseline === "number") base.robustness = comparison.robustness.baseline * 100;
  if (typeof comparison.robustness.candidate === "number") cand.robustness = comparison.robustness.candidate * 100;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Baseline vs candidate</CardTitle>
          <CardDescription>Dimensions moyennes (0–100) ; baseline en pointillés.</CardDescription>
        </CardHeader>
        <CardContent>
          <DimensionRadar
            values={cand}
            label={comparison.candidate.agent_label}
            comparison={base}
            comparisonLabel={comparison.baseline.agent_label}
            scale={100}
            height={300}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Taux par bras</CardTitle>
          <CardDescription>
            Bruit estimé sur les répétitions :{" "}
            {typeof comparison.noise.pooled_std === "number"
              ? `σ = ${formatNumber(comparison.noise.pooled_std, 2)} pts (${comparison.noise.repetitions} rép.)`
              : `${comparison.noise.default_std} pts par défaut (une seule répétition)`}
            .
          </CardDescription>
        </CardHeader>
        <Table dense>
          <TableHeader>
            <TableRow>
              <TableHead>Bras</TableHead>
              <TableHead className="text-right">Runs</TableHead>
              <TableHead className="text-right">Composite</TableHead>
              <TableHead className="text-right">Réussite</TableHead>
              <TableHead className="text-right">Garde-fou</TableHead>
              <TableHead className="text-right">Erreurs</TableHead>
              <TableHead className="text-right">Robustesse</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <ArmRow label="Baseline" arm={comparison.baseline} />
            <ArmRow label="Candidate" arm={comparison.candidate} />
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}

const CHANGE_META: Record<string, { label: string; tone: "red" | "green" | "amber" | "teal" | "neutral" }> = {
  appeared: { label: "Apparue", tone: "red" },
  disappeared: { label: "Disparue", tone: "green" },
  increased: { label: "En hausse", tone: "amber" },
  decreased: { label: "En baisse", tone: "teal" },
  stable: { label: "Stable", tone: "neutral" },
};

/** Error types appeared / disappeared and frequency changes. */
export function ErrorChangesCard({ comparison }: { comparison: Comparison }) {
  const e = comparison.errors;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Évolution des erreurs</CardTitle>
        <CardDescription>
          Part des runs avec erreur : {formatPercent(e.baseline_error_rate)} → {formatPercent(e.candidate_error_rate)}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid content-start gap-2 rounded-lg border border-red-200 p-3 dark:border-red-400/25">
            <p className="flex items-center gap-1.5 text-[13px] font-semibold text-red-700 dark:text-red-400">
              <TriangleAlert className="size-3.5" aria-hidden /> Types apparus ({e.appeared.length})
            </p>
            <div className="flex flex-wrap gap-1">
              {e.appeared.length ? e.appeared.map((c) => <ErrorTypeBadge key={c} code={c} />) : <span className="text-xs text-muted-foreground">Aucun</span>}
            </div>
          </div>
          <div className="grid content-start gap-2 rounded-lg border border-emerald-200 p-3 dark:border-emerald-400/25">
            <p className="flex items-center gap-1.5 text-[13px] font-semibold text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 className="size-3.5" aria-hidden /> Types disparus ({e.disappeared.length})
            </p>
            <div className="flex flex-wrap gap-1">
              {e.disappeared.length ? e.disappeared.map((c) => <ErrorTypeBadge key={c} code={c} />) : <span className="text-xs text-muted-foreground">Aucun</span>}
            </div>
          </div>
        </div>
      </CardContent>
      <Table dense>
        <TableHeader>
          <TableRow>
            <TableHead>Type</TableHead>
            <TableHead>Gravité max.</TableHead>
            <TableHead className="text-right">Baseline</TableHead>
            <TableHead className="text-right">Candidate</TableHead>
            <TableHead className="text-right">Δ fréquence</TableHead>
            <TableHead>Évolution</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {e.changes.length === 0 ? (
            <TableEmptyRow colSpan={6}>Aucune erreur détectée sur les deux bras.</TableEmptyRow>
          ) : (
            e.changes.map((c) => {
              const meta = CHANGE_META[c.change] ?? CHANGE_META.stable!;
              return (
                <TableRow key={c.error_type}>
                  <TableCell>
                    <ErrorTypeBadge code={c.error_type} />
                  </TableCell>
                  <TableCell>
                    <SeverityBadge severity={c.max_severity} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {c.baseline_count} <span className="text-[11px] text-muted-foreground">({formatPercent(c.baseline_rate)})</span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {c.candidate_count} <span className="text-[11px] text-muted-foreground">({formatPercent(c.candidate_rate)})</span>
                  </TableCell>
                  <TableCell className="text-right">
                    <DeltaIndicator
                      value={typeof c.delta_rate === "number" ? c.delta_rate * 100 : null}
                      higherIsBetter={false}
                      format={() => formatSignedPercent(c.delta_rate)}
                    />
                  </TableCell>
                  <TableCell>
                    <Badge tone={meta.tone}>{meta.label}</Badge>
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
    </Card>
  );
}

/** Statistics footnote. */
export function StatisticsNote({ comparison }: { comparison: Comparison }) {
  const s = comparison.statistics;
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-subtle-foreground">
      <ShieldAlert className="size-3.5" aria-hidden />
      Méthode : {s.method} · {s.significance_test} · α = {s.alpha} · graine {s.seed} · unité {s.unit} · seuil minimal de
      régression {s.min_regression_delta} pts.
      {comparison.generated_at ? (
        <SimpleTooltip content={comparison.generated_at}>
          <span tabIndex={0}>Calculé le {new Date(comparison.generated_at).toLocaleString("fr-FR")}</span>
        </SimpleTooltip>
      ) : null}
    </p>
  );
}
