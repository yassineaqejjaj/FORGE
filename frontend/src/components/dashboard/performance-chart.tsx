"use client";

import * as React from "react";
import { LineChart as LineChartIcon } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CHART_COLORS } from "@/components/ui/chart";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import type { Dashboard, DashboardKpis, DashboardTrendPoint } from "@/lib/api/dashboard";
import { formatCost, formatDateLong, formatMs, formatNumber, formatPercent, formatScore100 } from "@/lib/format";

import { TrendChart } from "./trend-chart";

type MetricKey = "score" | "pass" | "cost" | "latency" | "errors";

interface Metric {
  key: MetricKey;
  label: string;
  description: string;
  trendKey: keyof DashboardTrendPoint & string;
  kpi: (k: DashboardKpis) => number | null | undefined;
  format: (v: number) => string;
  tick?: (v: number) => string;
  domain: [number | "auto", number | "auto"];
}

/** One series at a time: a single colour keeps the chart calm (the selector names the metric). */
const SERIES_COLOR = CHART_COLORS[0] ?? "var(--chart-1)";

const METRICS: Metric[] = [
  {
    key: "score",
    label: "Score",
    description: "Score composite moyen par jour (0–100)",
    trendKey: "average_composite",
    kpi: (k) => k.average_composite,
    format: (v) => formatScore100(v),
    tick: (v) => formatNumber(v, 0),
    domain: [0, 100],
  },
  {
    key: "pass",
    label: "Réussite",
    description: "Part des évaluations au-dessus du seuil, par jour",
    trendKey: "pass_rate",
    kpi: (k) => k.pass_rate,
    format: (v) => formatPercent(v),
    domain: [0, 1],
  },
  {
    key: "cost",
    label: "Coût",
    description: "Coût estimé moyen par exécution, par jour",
    trendKey: "average_cost",
    kpi: (k) => k.average_cost,
    format: (v) => formatCost(v),
    domain: [0, "auto"],
  },
  {
    key: "latency",
    label: "Latence",
    description: "Temps de bout en bout moyen, par jour",
    trendKey: "average_latency_ms",
    kpi: (k) => k.average_latency_ms,
    format: (v) => formatMs(v),
    domain: [0, "auto"],
  },
  {
    key: "errors",
    label: "Erreurs",
    description: "Part des évaluations avec au moins une erreur détectée, par jour",
    trendKey: "error_rate",
    kpi: (k) => k.error_rate,
    format: (v) => formatPercent(v),
    domain: [0, 1],
  },
];

/** Below this number of days with data, a line chart says nothing: show the value instead. */
const MIN_DAYS_FOR_CHART = 3;

/** Level 2: one chart, one metric at a time, over the period chosen in the header. */
export function PerformanceChart({ data, className }: { data: Dashboard | undefined; className?: string }) {
  const [metricKey, setMetricKey] = React.useState<MetricKey>("score");
  const metric = METRICS.find((m) => m.key === metricKey) ?? METRICS[0]!;
  const daysWithData = data ? data.trends.filter((t) => typeof t[metric.trendKey] === "number").length : 0;
  const current = data ? metric.kpi(data.kpis) : null;

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Performance dans le temps</CardTitle>
        <CardDescription>{metric.description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="max-w-full overflow-x-auto [scrollbar-width:none]">
          <SegmentedControl
            aria-label="Métrique affichée"
            value={metricKey}
            onValueChange={(v) => setMetricKey(v as MetricKey)}
            options={METRICS.map((m) => ({ value: m.key, label: m.label }))}
          />
        </div>
        {!data ? (
          <Skeleton className="h-[200px] w-full" />
        ) : daysWithData >= MIN_DAYS_FOR_CHART ? (
          <TrendChart
            data={data.trends}
            dataKey={metric.trendKey}
            name={metric.label}
            color={SERIES_COLOR}
            valueFormatter={metric.format}
            tickFormatter={metric.tick}
            domain={metric.domain}
            height={200}
          />
        ) : (
          <div className="flex flex-wrap items-center gap-4 rounded-lg border border-dashed border-border px-4 py-4">
            <span
              className="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground"
              aria-hidden
            >
              <LineChartIcon className="size-5" />
            </span>
            <div className="grid gap-0.5">
              <span className="text-[13px] text-muted-foreground">{metric.label} sur la période</span>
              <span className="text-2xl font-semibold tabular-nums text-foreground">
                {typeof current === "number" ? metric.format(current) : "—"}
              </span>
            </div>
            <p className="max-w-md text-[12.5px] leading-relaxed text-muted-foreground sm:ml-auto">
              {data.first_activity ? <>Données disponibles depuis le {formatDateLong(data.first_activity)}. </> : null}
              {daysWithData === 0
                ? "Aucune exécution évaluée sur la période."
                : `${daysWithData} jour${daysWithData > 1 ? "s" : ""} avec des exécutions : la courbe s'affiche à partir de ${MIN_DAYS_FOR_CHART} jours.`}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
