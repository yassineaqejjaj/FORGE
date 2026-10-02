"use client";

import * as React from "react";
import { Lightbulb, ThumbsDown, ThumbsUp } from "lucide-react";

import { PriorityBadge, RecommendationCategoryBadge } from "@/components/domain/enum-badge";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { ScoreBadge } from "@/components/domain/score-badge";
import { SeverityBadge } from "@/components/domain/severity-badge";
import { Badge } from "@/components/ui/badge";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { useFeedbackReport, type FeedbackReport } from "@/lib/api/experiments";
import { formatDateTime, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ReportError {
  type?: string;
  label?: string;
  count?: number;
  runs?: number;
  severity?: string;
  examples?: string[];
}

interface ReportRecommendation {
  title?: string;
  category?: string;
  priority?: string;
  description?: string;
  rationale?: string;
  related_errors?: string[];
  related_criteria?: string[];
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/** Renders a `FeedbackReport` (scope run / benchmark / experiment) as produced by the API. */
export function FeedbackReportView({ report, className }: { report: FeedbackReport; className?: string }) {
  const errors = report.errors as ReportError[];
  const recommendations = report.recommendations as ReportRecommendation[];
  return (
    <div className={cn("grid gap-5", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-3xl text-[13.5px] leading-relaxed text-foreground">{report.summary}</p>
        <div className="flex items-center gap-2">
          {typeof report.score === "number" ? <ScoreBadge value={report.score} size="md" /> : null}
          <Badge tone="neutral" variant="outline">
            {report.generator.startsWith("llm") ? `Généré par ${report.generator.replace("llm:", "")}` : "Déterministe"}
          </Badge>
        </div>
      </div>
      {report.redacted ? (
        <RedactedNotice
          variant="inline"
          title="Rapport partiellement masqué"
          description="Certaines preuves proviennent de scénarios privés."
        />
      ) : null}

      {report.priority_actions.length ? (
        <div className="rounded-lg border border-brand/30 bg-brand-soft/40 p-3">
          <p className="mb-1.5 text-[11.5px] font-semibold uppercase tracking-wide text-subtle-foreground">Actions prioritaires</p>
          <ol className="grid gap-1 text-[13px]">
            {report.priority_actions.map((a, i) => (
              <li key={i} className="flex gap-2">
                <span className="font-semibold tabular-nums text-brand">{i + 1}.</span>
                {a}
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid content-start gap-2">
          <h4 className="flex items-center gap-1.5 text-[13px] font-semibold">
            <ThumbsUp className="size-3.5 text-emerald-600" aria-hidden /> Points forts
          </h4>
          {report.strengths.length ? (
            <ul className="grid gap-1 text-[13px] text-muted-foreground">
              {report.strengths.map((s) => (
                <li key={s} className="flex gap-2">
                  <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-emerald-500" aria-hidden />
                  {s}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-subtle-foreground">Aucun critère ≥ 0,8.</p>
          )}
        </div>
        <div className="grid content-start gap-2">
          <h4 className="flex items-center gap-1.5 text-[13px] font-semibold">
            <ThumbsDown className="size-3.5 text-red-600" aria-hidden /> Points faibles
          </h4>
          {report.weaknesses.length ? (
            <ul className="grid gap-1 text-[13px] text-muted-foreground">
              {report.weaknesses.map((s) => (
                <li key={s} className="flex gap-2">
                  <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-red-500" aria-hidden />
                  {s}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-subtle-foreground">Aucun critère &lt; 0,6.</p>
          )}
        </div>
      </div>

      {errors.length ? (
        <div className="grid gap-2">
          <h4 className="text-[13px] font-semibold">Erreurs regroupées</h4>
          <ul className="grid gap-2">
            {errors.map((e, i) => (
              <li key={`${e.type}-${i}`} className="rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  {e.type ? <ErrorTypeBadge code={e.type} label={e.label} count={e.count} /> : null}
                  {e.severity ? <SeverityBadge severity={e.severity} /> : null}
                  {typeof e.runs === "number" ? (
                    <span className="text-xs text-muted-foreground">{formatNumber(e.runs, 0)} run(s) concerné(s)</span>
                  ) : null}
                </div>
                {asStringArray(e.examples).length ? (
                  <p className="mt-1.5 text-[12.5px] text-muted-foreground">{asStringArray(e.examples)[0]}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {recommendations.length ? (
        <div className="grid gap-2">
          <h4 className="flex items-center gap-1.5 text-[13px] font-semibold">
            <Lightbulb className="size-3.5 text-amber-500" aria-hidden /> Recommandations
          </h4>
          <ul className="grid gap-2">
            {recommendations.map((r, i) => (
              <li key={`${r.title}-${i}`} className="grid gap-1.5 rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  {r.priority ? <PriorityBadge value={r.priority} /> : null}
                  {r.category ? <RecommendationCategoryBadge value={r.category} /> : null}
                  <span className="text-[13px] font-medium">{r.title}</span>
                </div>
                {r.description ? <p className="text-[13px] text-foreground/90">{r.description}</p> : null}
                {r.rationale ? <p className="text-[12.5px] text-muted-foreground">Pourquoi : {r.rationale}</p> : null}
                {asStringArray(r.related_errors).length || asStringArray(r.related_criteria).length ? (
                  <div className="flex flex-wrap gap-1">
                    {asStringArray(r.related_errors).map((c) => (
                      <ErrorTypeBadge key={c} code={c} />
                    ))}
                    {asStringArray(r.related_criteria).map((c) => (
                      <Badge key={c} mono variant="outline">
                        {c}
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="text-[11.5px] text-subtle-foreground">Rapport généré le {formatDateTime(report.created_at)}</p>
    </div>
  );
}

/** Loads `GET /feedback-reports/{id}` and renders it. */
export function FeedbackReportById({ id, className }: { id: string | null | undefined; className?: string }) {
  const query = useFeedbackReport(id);
  if (!id) return <p className="text-[13px] text-muted-foreground">Aucun rapport de feedback disponible.</p>;
  if (query.isPending)
    return (
      <div className={cn("grid gap-3", className)}>
        <Skeleton className="h-5 w-2/3" />
        <SkeletonText lines={4} />
      </div>
    );
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} size="sm" />;
  return <FeedbackReportView report={query.data} className={className} />;
}
