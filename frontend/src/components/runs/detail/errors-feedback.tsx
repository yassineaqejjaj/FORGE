"use client";

import * as React from "react";
import { Bug, ClipboardCopy, Lightbulb, ListChecks, ThumbsDown, ThumbsUp } from "lucide-react";
import { toast } from "sonner";

import { EvaluatorKindBadge, PriorityBadge, RecommendationCategoryBadge } from "@/components/domain/enum-badge";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { ScoreBadge } from "@/components/domain/score-badge";
import { SeverityBadge } from "@/components/domain/severity-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/client";
import {
  readEvidence,
  readFeedbackErrors,
  readRecommendations,
  type FeedbackReport,
  type RunError,
} from "@/lib/api/runs";
import { SEVERITY_RANK, type ErrorSeverity } from "@/lib/enums";
import { formatDateTime } from "@/lib/format";
import { copyToClipboard } from "@/lib/utils";
import { EventRef, EvidenceList, EvidenceText } from "./evidence";
import { useRunDetail } from "./run-detail-context";

/* -------------------------------------------------------------------------- */
/* Errors                                                                     */
/* -------------------------------------------------------------------------- */

/** Classified errors of the round (type, severity, description, evidence, evaluator, trace event). */
export function ErrorsSection({ errors, names }: { errors: RunError[]; names: Map<string, string> }) {
  const ctx = useRunDetail();
  if (!errors.length)
    return (
      <EmptyState size="sm" icon={<Bug />} title="Aucune erreur détectée" description="Ni les règles, ni les juges, ni l'exécution n'ont signalé d'erreur sur ce round." />
    );
  const sorted = [...errors].sort(
    (a, b) => (SEVERITY_RANK[b.severity as ErrorSeverity] ?? 0) - (SEVERITY_RANK[a.severity as ErrorSeverity] ?? 0),
  );
  return (
    <ul className="grid gap-2.5">
      {sorted.map((err) => {
        const evidence = readEvidence(err.evidence);
        return (
          <li key={err.id} className="rounded-xl border border-border bg-card p-4 shadow-panel">
            <div className="flex flex-wrap items-center gap-2">
              <ErrorTypeBadge code={err.error_type} label={err.label} size="md" />
              <SeverityBadge severity={err.severity} size="md" withPrefix />
              {typeof err.trace_event_seq === "number" ? (
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  événement <EventRef seq={err.trace_event_seq} />
                </span>
              ) : null}
              {err.round === null || err.round === undefined ? <Badge tone="neutral" variant="outline">Exécution</Badge> : null}
              <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
                {err.evaluator_kind ? <EvaluatorKindBadge value={err.evaluator_kind} withTooltip={false} /> : null}
                <span className="font-mono">{err.evaluator_key}</span>
              </span>
            </div>
            <div className="mt-2 grid gap-2">
              {err.redacted ? (
                <RedactedNotice variant="inline" title="Description masquée (scénario privé)" />
              ) : (
                <p className="text-[13px] leading-relaxed">
                  <EvidenceText text={err.description} />
                </p>
              )}
              {evidence.length && !err.redacted ? <EvidenceList evidence={evidence} compact /> : null}
              {err.criterion_key ? (
                <p className="text-xs text-muted-foreground">
                  Critère concerné :{" "}
                  <button type="button" className="font-medium text-primary hover:underline" onClick={() => ctx?.openProvenance(err.criterion_key!)}>
                    {names.get(err.criterion_key) ?? err.criterion_key}
                  </button>
                </p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/* -------------------------------------------------------------------------- */
/* Feedback                                                                   */
/* -------------------------------------------------------------------------- */

function FeedbackBody({ report }: { report: FeedbackReport }) {
  const recommendations = readRecommendations(report.recommendations);
  const errorGroups = readFeedbackErrors(report.errors);
  const copyJson = async () => {
    const ok = await copyToClipboard(JSON.stringify(report, null, 2));
    if (ok) toast.success("Rapport de feedback copié (JSON).");
    else toast.error("Copie impossible dans ce navigateur.");
  };
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="grid gap-1">
              <CardTitle className="flex flex-wrap items-center gap-2">
                Synthèse
                <ScoreBadge value={report.score} />
                <Badge tone={report.generator.startsWith("llm") ? "violet" : "neutral"} variant="outline">
                  {report.generator.startsWith("llm") ? `Enrichi par ${report.generator.replace("llm:", "")}` : "Déterministe"}
                </Badge>
              </CardTitle>
              <CardDescription>Généré le {formatDateTime(report.created_at)}{report.round ? ` · round ${report.round}` : ""}</CardDescription>
            </div>
            <Button variant="secondary" size="sm" leftIcon={<ClipboardCopy aria-hidden />} onClick={() => void copyJson()}>
              Copier le JSON
            </Button>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4">
          {report.redacted ? <RedactedNotice description="Les extraits et preuves de ce rapport proviennent d'un scénario privé : ils sont masqués." /> : null}
          <p className="text-[13.5px] leading-relaxed">{report.summary}</p>
          {report.priority_actions.length ? (
            <div className="rounded-lg border border-orange-200 bg-orange-50/60 px-3.5 py-3 dark:border-orange-400/25 dark:bg-orange-400/10">
              <h4 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-orange-800 dark:text-orange-200">
                <ListChecks className="size-3.5" aria-hidden />
                Actions prioritaires
              </h4>
              <ol className="grid list-decimal gap-1 pl-5 text-[13px]">
                {report.priority_actions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ol>
            </div>
          ) : null}
          <div className="grid gap-4 md:grid-cols-2">
            <div className="grid content-start gap-1.5">
              <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
                <ThumbsUp className="size-3.5" aria-hidden />
                Points forts ({report.strengths.length})
              </h4>
              {report.strengths.length ? (
                <ul className="grid gap-1 text-[13px]">
                  {report.strengths.map((s, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-emerald-500" aria-hidden />
                      {s}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-muted-foreground">Aucun critère ≥ 0,8.</p>
              )}
            </div>
            <div className="grid content-start gap-1.5">
              <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-red-700 dark:text-red-300">
                <ThumbsDown className="size-3.5" aria-hidden />
                Points faibles ({report.weaknesses.length})
              </h4>
              {report.weaknesses.length ? (
                <ul className="grid gap-1 text-[13px]">
                  {report.weaknesses.map((s, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-red-500" aria-hidden />
                      {s}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-muted-foreground">Aucun critère &lt; 0,6.</p>
              )}
            </div>
          </div>
          {errorGroups.length ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-muted-foreground">Erreurs regroupées :</span>
              {errorGroups.map((g) => (
                <ErrorTypeBadge key={g.type} code={g.type} label={g.label} count={g.count} />
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {recommendations.length ? (
        <div className="grid gap-3 md:grid-cols-2">
          {recommendations.map((r, i) => {
            const evidence = readEvidence(r.evidence);
            return (
              <Card key={i}>
                <CardContent className="grid gap-2 pt-4">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Lightbulb className="size-4 text-amber-500" aria-hidden />
                    <PriorityBadge value={r.priority} />
                    <RecommendationCategoryBadge value={r.category} />
                  </div>
                  <h4 className="text-sm font-semibold">{r.title}</h4>
                  {r.description ? <p className="text-[13px] leading-relaxed">{r.description}</p> : null}
                  {r.rationale ? <p className="text-xs leading-relaxed text-muted-foreground">{r.rationale}</p> : null}
                  {r.related_errors?.length || r.related_criteria?.length ? (
                    <div className="flex flex-wrap gap-1">
                      {r.related_errors?.map((e) => <ErrorTypeBadge key={e} code={e} />)}
                      {r.related_criteria?.map((c) => (
                        <Badge key={c} tone="neutral" variant="outline" mono>
                          {c}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                  {evidence.length ? <EvidenceList evidence={evidence} compact /> : null}
                </CardContent>
              </Card>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

/** Run FeedbackReport (summary, strengths, weaknesses, recommendations, priority actions, JSON copy). */
export function FeedbackSection({
  report,
  loading,
  error,
  onRetry,
  pending,
}: {
  report: FeedbackReport | undefined;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  /** The run is still being executed / evaluated. */
  pending: boolean;
}) {
  if (loading) return <Skeleton className="h-48 w-full" />;
  if (!report) {
    if (pending || (isApiError(error) && error.isNotFound))
      return (
        <EmptyState
          size="sm"
          icon={<Lightbulb />}
          title={pending ? "Feedback en préparation" : "Pas de rapport de feedback"}
          description={pending ? "Le rapport sera disponible à la fin de l'évaluation." : "Aucun rapport de feedback n'a été produit pour ce round."}
        />
      );
    return <ErrorState error={error} onRetry={onRetry} size="sm" />;
  }
  return <FeedbackBody report={report} />;
}
