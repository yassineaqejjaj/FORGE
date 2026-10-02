"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ClipboardCheck, Crosshair, Info, Users } from "lucide-react";
import { CartesianGrid, ReferenceLine, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";

import { CalibrationStatusBadge } from "@/components/domain/enum-badge";
import { KpiCard } from "@/components/domain/kpi-card";
import { FilterBar, FilterSelect } from "@/components/runs/filter-controls";
import { useSearchState } from "@/components/runs/use-search-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CHART_COLORS, ChartContainer, chartAxisProps } from "@/components/ui/chart";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { JudgesAreaTabs } from "@/components/layout/area-tabs";
import { useCalibration, useJudgeOptions, type CalibrationMetrics, type CalibrationReport, type ScorePair } from "@/lib/api/calibration";
import { useCriteriaCatalog, useGoldDatasets } from "@/lib/api/reviews";
import { formatNumber, formatPercent, formatScore, formatSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

function corr(v: number | null | undefined) {
  return typeof v === "number" ? formatNumber(v, 2) : "—";
}

function MetricsTable({ rows, empty }: { rows: CalibrationMetrics[]; empty: string }) {
  if (!rows.length) return <p className="py-6 text-center text-[13px] text-muted-foreground">{empty}</p>;
  return (
    <Table dense containerClassName="rounded-lg border border-border">
      <TableHeader>
        <TableRow>
          <TableHead>Juge / critère</TableHead>
          <TableHead className="text-right">n</TableHead>
          <TableHead className="text-right">Accord</TableHead>
          <TableHead className="text-right">Écart abs. moyen</TableHead>
          <TableHead className="text-right">Biais IA − humain</TableHead>
          <TableHead className="text-right">Spearman</TableHead>
          <TableHead className="text-right">Pearson</TableHead>
          <TableHead className="text-right">Kappa pondéré</TableHead>
          <TableHead>Statut</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.key}>
            <TableCell className="max-w-[18rem]">
              <div className="grid min-w-0">
                <span className="truncate font-medium">{r.label}</span>
                <span className="truncate font-mono text-[11px] text-muted-foreground">
                  {[r.judge_key, r.criterion_key].filter(Boolean).join(" · ") || r.key}
                </span>
              </div>
            </TableCell>
            <TableCell className="text-right tabular-nums">{formatNumber(r.n, 0)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatPercent(r.agreement_rate)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatScore(r.mean_abs_error)}</TableCell>
            <TableCell className="text-right tabular-nums">{typeof r.bias === "number" ? formatSigned(r.bias, { digits: 2 }) : "—"}</TableCell>
            <TableCell className="text-right tabular-nums">{corr(r.spearman)}</TableCell>
            <TableCell className="text-right tabular-nums">{corr(r.pearson)}</TableCell>
            <TableCell className="text-right font-medium tabular-nums">{corr(r.kappa)}</TableCell>
            <TableCell>
              <CalibrationStatusBadge value={r.status} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

interface PointDatum extends ScorePair {
  x: number;
  y: number;
}

function PairsScatter({ report }: { report: CalibrationReport }) {
  const router = useRouter();
  const tolerance = report.thresholds.agreement_tolerance ?? 0.2;
  const data: PointDatum[] = report.pairs.map((p) => ({ ...p, x: p.ai, y: p.human }));
  const agree = data.filter((d) => Math.abs(d.x - d.y) <= tolerance).length;
  return (
    <div className="grid gap-2">
      <ChartContainer
        height={340}
        label={`Nuage de points score IA (abscisse) contre score humain (ordonnée), ${data.length} paires, ${agree} dans la tolérance de ${formatScore(tolerance)}.`}
      >
        <ScatterChart margin={{ top: 12, right: 16, bottom: 28, left: 4 }}>
          <CartesianGrid stroke="var(--chart-grid)" />
          <XAxis
            type="number"
            dataKey="x"
            domain={[0, 1]}
            ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]}
            tickFormatter={(v: number) => formatNumber(v, 1)}
            name="Score IA"
            label={{ value: "Score IA (normalisé)", position: "insideBottom", offset: -16, fill: "var(--muted-foreground)", fontSize: 11 }}
            {...chartAxisProps}
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={[0, 1]}
            ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]}
            tickFormatter={(v: number) => formatNumber(v, 1)}
            name="Score humain"
            width={44}
            label={{ value: "Score humain", angle: -90, position: "insideLeft", offset: 12, fill: "var(--muted-foreground)", fontSize: 11 }}
            {...chartAxisProps}
          />
          <ZAxis range={[56, 56]} />
          <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="var(--chart-axis)" strokeDasharray="4 4" ifOverflow="hidden" />
          <ReferenceLine segment={[{ x: 0, y: tolerance }, { x: 1 - tolerance, y: 1 }]} stroke="var(--border-strong)" strokeWidth={1} ifOverflow="hidden" />
          <ReferenceLine segment={[{ x: tolerance, y: 0 }, { x: 1, y: 1 - tolerance }]} stroke="var(--border-strong)" strokeWidth={1} ifOverflow="hidden" />
          <Tooltip
            cursor={{ strokeDasharray: "3 3", stroke: "var(--border-strong)" }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as PointDatum | undefined;
              if (!active || !p) return null;
              const gap = p.x - p.y;
              return (
                <div className="min-w-48 rounded-lg border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-lg">
                  <p className="mb-1 font-mono font-medium text-foreground">{p.criterion_key}</p>
                  <ul className="grid gap-0.5 tabular-nums">
                    <li className="flex justify-between gap-3"><span className="text-muted-foreground">IA</span><span>{formatScore(p.x)}</span></li>
                    <li className="flex justify-between gap-3"><span className="text-muted-foreground">Humain</span><span>{formatScore(p.y)}</span></li>
                    <li className="flex justify-between gap-3"><span className="text-muted-foreground">Écart</span><span>{formatSigned(gap, { digits: 2 })}</span></li>
                    {p.judge_key ? <li className="flex justify-between gap-3"><span className="text-muted-foreground">Juge</span><span className="font-mono">{p.judge_key}</span></li> : null}
                  </ul>
                  <p className="mt-1.5 text-[11px] text-muted-foreground">Cliquer pour ouvrir le run</p>
                </div>
              );
            }}
          />
          <Scatter
            data={data}
            fill={CHART_COLORS[0]}
            fillOpacity={0.75}
            stroke="var(--card)"
            strokeWidth={2}
            isAnimationActive={false}
            cursor="pointer"
            onClick={(point: unknown) => {
              const runId = (point as { payload?: PointDatum } | undefined)?.payload?.run_id;
              if (runId) router.push(`/runs/${runId}?criterion=${encodeURIComponent((point as { payload: PointDatum }).payload.criterion_key)}`);
            }}
          />
        </ScatterChart>
      </ChartContainer>
      <p className="text-xs text-muted-foreground">
        Diagonale pointillée : accord parfait. Lignes fines : bornes de tolérance d&apos;accord (|écart| ≤ {formatScore(tolerance)}) — {agree} / {data.length} paires dans la
        bande.
        {report.pairs_truncated ? " Affichage limité aux premières paires ; les métriques portent sur toutes les paires." : ""}
      </p>
    </div>
  );
}

function ThresholdsCard({ thresholds }: { thresholds: Record<string, number> }) {
  const t = (k: string, fallback: number) => thresholds[k] ?? fallback;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2">
          <Info className="size-4 text-muted-foreground" aria-hidden />
          Lecture des statuts
        </CardTitle>
        <CardDescription>Paires (score IA, score humain) normalisées 0–1, par run × critère.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 text-[13px]">
        <ul className="grid gap-2">
          <li className="flex items-start gap-2">
            <CalibrationStatusBadge value="calibrated" withTooltip={false} />
            <span>kappa ≥ {formatNumber(t("calibrated_kappa", 0.6))} et accord ≥ {formatPercent(t("calibrated_agreement", 0.7))}</span>
          </li>
          <li className="flex items-start gap-2">
            <CalibrationStatusBadge value="weak" withTooltip={false} />
            <span>kappa ≥ {formatNumber(t("weak_kappa", 0.4))}</span>
          </li>
          <li className="flex items-start gap-2">
            <CalibrationStatusBadge value="uncalibrated" withTooltip={false} />
            <span>en dessous</span>
          </li>
          <li className="flex items-start gap-2">
            <CalibrationStatusBadge value="insufficient_data" withTooltip={false} />
            <span>moins de {formatNumber(t("min_pairs", 10), 0)} paires</span>
          </li>
        </ul>
        <dl className="grid gap-1.5 border-t border-border pt-3 text-xs text-muted-foreground">
          <div><dt className="inline font-medium text-foreground">Accord</dt> : part des paires avec |IA − humain| ≤ {formatNumber(t("agreement_tolerance", 0.2))}.</div>
          <div><dt className="inline font-medium text-foreground">Kappa pondéré</dt> : kappa de Cohen quadratique, notes ramenées à des entiers 0–5.</div>
          <div><dt className="inline font-medium text-foreground">Biais</dt> : moyenne de (IA − humain) ; positif = juge plus indulgent que les humains.</div>
        </dl>
      </CardContent>
    </Card>
  );
}

/** `/calibration` — agreement between AI judges and human evaluators (docs §9.4). */
export function CalibrationView() {
  const search = useSearchState();
  const params = { judge_id: search.get("judge"), criterion_key: search.get("criterion"), dataset_id: search.get("dataset") };
  const report = useCalibration(params);
  const judges = useJudgeOptions();
  const criteria = useCriteriaCatalog();
  const datasets = useGoldDatasets();
  const data = report.data;
  const overall = data?.overall;

  return (
    <>
      <PageHeader
        eyebrow="Configuration · Juges"
        title="Calibration"
        icon={<Crosshair />}
        description="Les juges IA sont-ils d'accord avec les humains ? Accord, corrélations et kappa pondéré, par juge et par critère."
        meta={overall ? <CalibrationStatusBadge value={overall.status} size="md" /> : null}
        actions={
          <Button asChild variant="secondary">
            <Link href="/reviews">
              <ClipboardCheck aria-hidden />
              File de revue
            </Link>
          </Button>
        }
      >
        <JudgesAreaTabs />
      </PageHeader>

      <FilterBar activeCount={search.countActive(["judge", "criterion", "dataset"])} onReset={() => search.clear()} className="mb-4">
        <FilterSelect
          id="calib-judge"
          label="Juge"
          value={params.judge_id}
          onChange={(judge) => search.set({ judge })}
          options={(judges.data?.items ?? []).map((j) => ({ value: j.id, label: `${j.name} · v${j.version}`, description: `${j.key} · ${j.model}` }))}
          loading={judges.isPending}
          className="col-span-2"
        />
        <FilterSelect
          id="calib-criterion"
          label="Critère"
          value={params.criterion_key}
          onChange={(criterion) => search.set({ criterion })}
          options={(criteria.data ?? []).filter((c) => c.judged).map((c) => ({ value: c.key, label: c.name, description: c.key }))}
          loading={criteria.isPending}
          className="col-span-2"
        />
        <FilterSelect
          id="calib-dataset"
          label="Jeu de données gold"
          value={params.dataset_id}
          onChange={(dataset) => search.set({ dataset })}
          options={(datasets.data?.items ?? []).map((d) => ({ value: d.id, label: d.name, description: `${d.items_count} runs` }))}
          loading={datasets.isPending}
          allLabel="Tous les runs"
          className="col-span-2"
        />
      </FilterBar>

      {report.isError && !data ? (
        <ErrorState error={report.error} onRetry={() => void report.refetch()} />
      ) : (
        <div className={cn("grid gap-4", report.isPlaceholderData && "opacity-60")}>
          <section aria-label="Indicateurs" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <KpiCard label="Runs notés" icon={<Users />} value={formatNumber(data?.n_runs ?? 0, 0)} hint={`${formatNumber(data?.n_human_scores ?? 0, 0)} scores humains`} loading={report.isPending} />
            <KpiCard label="Paires IA / humain" value={formatNumber(overall?.n ?? 0, 0)} loading={report.isPending} tone="blue" />
            <KpiCard label="Taux d'accord" value={formatPercent(overall?.agreement_rate)} loading={report.isPending} tone="green" hint={`|écart| ≤ ${formatScore(data?.thresholds.agreement_tolerance ?? 0.2)}`} />
            <KpiCard label="Kappa pondéré" value={corr(overall?.kappa)} loading={report.isPending} tone="violet" hint={overall ? <CalibrationStatusBadge value={overall.status} /> : undefined} />
            <KpiCard label="Écart absolu moyen" value={formatScore(overall?.mean_abs_error)} loading={report.isPending} tone="amber" />
            <KpiCard label="Spearman" value={corr(overall?.spearman)} loading={report.isPending} tone="teal" hint={`Pearson ${corr(overall?.pearson)}`} />
          </section>

          {report.isPending ? (
            <Skeleton className="h-96 w-full rounded-xl" />
          ) : data && data.pairs.length === 0 && (overall?.n ?? 0) === 0 ? (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
              <EmptyState
                icon={<Crosshair />}
                title="Aucune paire IA / humain pour ces filtres"
                description="La calibration se calcule dès que des évaluateurs notent des runs déjà jugés par l'IA. Commencez par la file de revue (les runs où les juges divergent le plus sont prioritaires)."
                action={
                  <Button asChild size="sm">
                    <Link href="/reviews">Ouvrir la file de revue</Link>
                  </Button>
                }
              />
              <ThresholdsCard thresholds={data.thresholds} />
            </div>
          ) : data ? (
            <>
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle>Score IA vs score humain</CardTitle>
                    <CardDescription>Chaque point est un run × critère ; un point éloigné de la diagonale est un désaccord.</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <PairsScatter report={data} />
                  </CardContent>
                </Card>
                <ThresholdsCard thresholds={data.thresholds} />
              </div>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2">
                    Métriques détaillées
                    {data.filters.judge || data.filters.criterion_key || data.filters.dataset ? (
                      <Badge tone="neutral" variant="outline">
                        {[data.filters.judge, data.filters.criterion_key, data.filters.dataset].filter(Boolean).join(" · ")}
                      </Badge>
                    ) : null}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <Tabs defaultValue="judge">
                    <TabsList variant="pills">
                      <TabsTrigger value="judge" count={data.by_judge.length}>Par juge</TabsTrigger>
                      <TabsTrigger value="criterion" count={data.by_criterion.length}>Par critère</TabsTrigger>
                      <TabsTrigger value="cross" count={data.by_judge_criterion.length}>Juge × critère</TabsTrigger>
                    </TabsList>
                    <TabsContent value="judge">
                      <MetricsTable rows={data.by_judge} empty="Aucun juge avec des paires." />
                    </TabsContent>
                    <TabsContent value="criterion">
                      <MetricsTable rows={data.by_criterion} empty="Aucun critère avec des paires." />
                    </TabsContent>
                    <TabsContent value="cross">
                      <MetricsTable rows={data.by_judge_criterion} empty="Aucune combinaison juge × critère." />
                    </TabsContent>
                  </Tabs>
                </CardContent>
              </Card>
            </>
          ) : null}
        </div>
      )}
    </>
  );
}
