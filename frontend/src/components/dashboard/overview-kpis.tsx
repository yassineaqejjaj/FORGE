"use client";

import Link from "next/link";
import { Activity, ArrowRight, Coins, Gauge, Info, ShieldCheck } from "lucide-react";

import { DeltaIndicator } from "@/components/domain/delta-indicator";
import { KpiCard, KpiCardSkeleton } from "@/components/domain/kpi-card";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";
import type { Dashboard } from "@/lib/api/dashboard";
import { formatCost, formatNumber, formatPercent, formatScore100, plural } from "@/lib/format";
import { scoreTone } from "@/lib/scores";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

/** Absolute difference in points (scores 0–100, or rates ×100). */
function pointsDelta(current: number | null | undefined, previous: number | null | undefined, scale = 1) {
  if (typeof current !== "number" || typeof previous !== "number") return null;
  return (current - previous) * scale;
}

/** Relative change in % (null when the previous value is missing or zero). */
function relativeDelta(current: number | null | undefined, previous: number | null | undefined) {
  if (typeof current !== "number" || typeof previous !== "number" || previous === 0) return null;
  return ((current - previous) / previous) * 100;
}

/** Inline definition: the value never depends on a colour or a hover only (the label says it). */
export function Definition({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <SimpleTooltip content={text} side="bottom" align="start">
      <span
        className="inline-flex cursor-help items-center gap-1 underline decoration-dotted decoration-border-strong underline-offset-2"
        tabIndex={0}
      >
        {children}
        <Info className="size-3 text-subtle-foreground" aria-hidden />
        <span className="sr-only"> — {text}</span>
      </span>
    </SimpleTooltip>
  );
}

const PASS_DEFINITION =
  "Évaluations dont le score composite atteint le seuil de réussite de leur configuration, sans garde-fou déclenché.";
const RELIABILITY_DEFINITION =
  "Évaluations sans aucune erreur critique (fuite de données, contamination…) et sans garde-fou déclenché.";
const ERROR_DEFINITION =
  "Évaluations avec au moins une erreur détectée par une règle ou un juge, toutes gravités confondues (une erreur mineure suffit).";
const INTERRUPTED_DEFINITION =
  "Exécutions qui n'ont pas pu aller au bout (erreur technique, délai dépassé, budget) : elles comptent 0 au score.";

/** Level 1: average quality, its evolution and the share above the pass threshold. */
function QualityCard({ data, days }: { data: Dashboard; days: number }) {
  const { kpis, previous_kpis: prev } = data;
  const score = kpis.average_composite;
  const delta = pointsDelta(score, prev?.average_composite);
  const tone = typeof score === "number" ? toneClasses(scoreTone(score)) : null;
  return (
    <section
      aria-labelledby="kpi-quality"
      className="relative flex h-full flex-col gap-3 overflow-hidden rounded-xl border border-border bg-card p-5 shadow-panel"
    >
      <span className="absolute inset-x-0 top-0 h-1 bg-brand" aria-hidden />
      <h2 id="kpi-quality" className="flex items-center gap-2 text-[13px] font-semibold text-foreground">
        <Gauge className="size-4 text-brand" aria-hidden />
        Qualité moyenne
      </h2>
      {typeof score === "number" ? (
        <>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className={cn("text-4xl font-semibold tracking-tight tabular-nums", tone?.text)}>
              {formatScore100(score)}
            </span>
            <span className="text-sm font-medium text-muted-foreground">/ 100</span>
            {delta !== null ? (
              <span className="inline-flex items-center gap-1.5 text-[13px]">
                <DeltaIndicator value={delta} unit="pts" size="md" />
                <span className="text-muted-foreground">vs {days} j précédents</span>
              </span>
            ) : null}
          </div>
          <p className="text-[13px] text-muted-foreground">
            <span className="font-semibold text-foreground">{formatPercent(kpis.pass_rate)}</span>{" "}
            <Definition text={PASS_DEFINITION}>des évaluations au-dessus du seuil</Definition>
            {" · "}
            {plural(kpis.evaluated_runs, "évaluation", "évaluations")}
          </p>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">Aucune exécution évaluée sur la période.</p>
      )}
      <Link
        href="/results"
        className="mt-auto inline-flex w-fit items-center gap-1 rounded text-[12.5px] font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        Résultats détaillés <ArrowRight className="size-3.5" aria-hidden />
      </Link>
    </section>
  );
}

/** Mobile: quality, then « À traiter » (order-2), then these. From sm up, the four KPIs come first. */
const SECONDARY = "order-3 grid sm:order-1 2xl:col-span-3";

/** Quality first, then reliability, cost and activity — four indicators instead of eight. */
export function OverviewKpis({ data, days }: { data: Dashboard | undefined; days: number }) {
  if (!data) {
    return (
      <>
        <div className="order-1 2xl:col-span-3">
          <div className="h-full rounded-xl border border-border bg-card p-5 shadow-panel" aria-hidden>
            <Skeleton className="h-4 w-28" />
            <Skeleton className="mt-4 h-10 w-32" />
            <Skeleton className="mt-3 h-3 w-48" />
          </div>
        </div>
        {Array.from({ length: 3 }, (_, i) => (
          <KpiCardSkeleton key={i} className={SECONDARY} />
        ))}
      </>
    );
  }
  const { kpis, previous_kpis: prev, counts } = data;
  const vs = `vs ${days} j précédents`;
  return (
    <>
      <div className="order-1 2xl:col-span-3">
        <QualityCard data={data} days={days} />
      </div>
      <div className={SECONDARY}>
        <KpiCard
          label="Fiabilité"
          icon={<ShieldCheck aria-hidden />}
          tone="green"
          value={formatPercent(kpis.reliability_rate)}
          delta={
            prev
              ? {
                  value: pointsDelta(kpis.reliability_rate, prev.reliability_rate, 100),
                  unit: "pts",
                  digits: 0,
                  label: vs,
                }
              : undefined
          }
          hint={
            <div className="grid gap-0.5">
              <Definition text={RELIABILITY_DEFINITION}>sans erreur critique ni garde-fou</Definition>
              <span>
                {formatPercent(kpis.error_rate)}{" "}
                <Definition text={ERROR_DEFINITION}>avec une erreur détectée</Definition>
              </span>
              <span>
                {formatNumber(kpis.interrupted_runs, 0)}{" "}
                <Definition text={INTERRUPTED_DEFINITION}>
                  exécution{kpis.interrupted_runs > 1 ? "s" : ""} interrompue
                  {kpis.interrupted_runs > 1 ? "s" : ""}
                </Definition>
              </span>
            </div>
          }
        />
      </div>
      <div className={SECONDARY}>
        <KpiCard
          label="Coût moyen"
          icon={<Coins aria-hidden />}
          tone="neutral"
          value={formatCost(kpis.average_cost)}
          unit="par exécution"
          delta={
            prev
              ? {
                  value: relativeDelta(kpis.average_cost, prev.average_cost),
                  unit: "%",
                  digits: 0,
                  kind: "cost",
                  label: vs,
                }
              : undefined
          }
          hint={
            kpis.total_cost !== null && kpis.total_cost !== undefined
              ? `Total : ${formatCost(kpis.total_cost)}`
              : undefined
          }
        />
      </div>
      <div className={SECONDARY}>
        <KpiCard
          label="Exécutions"
          icon={<Activity aria-hidden />}
          tone="blue"
          value={formatNumber(counts.runs, 0)}
          delta={
            prev
              ? {
                  value: relativeDelta(counts.runs, prev.runs),
                  unit: "%",
                  digits: 0,
                  kind: "neutral",
                  label: vs,
                }
              : undefined
          }
          hint={`${formatNumber(kpis.completed_runs, 0)} terminées · ${formatNumber(kpis.evaluated_runs, 0)} évaluées`}
          href="/runs"
        />
      </div>
    </>
  );
}
