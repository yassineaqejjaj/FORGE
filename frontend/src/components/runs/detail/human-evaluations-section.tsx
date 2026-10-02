"use client";

import * as React from "react";
import { ClipboardCheck, EyeOff, UserRound } from "lucide-react";

import { RequireRole } from "@/components/auth/require-role";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { RelativeTime } from "@/components/domain/relative-time";
import { ScoreBar } from "@/components/domain/score-bar";
import { UserAvatar } from "@/components/domain/user-avatar";
import { HumanEvaluationForm } from "@/components/reviews/human-evaluation-form";
import { aiScoresFrom, groupByEvaluator, reviewCriteriaFor } from "@/components/reviews/review-criteria";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useCriteriaCatalog, useHumanEvaluations } from "@/lib/api/reviews";
import { isRunActive, type RunDetail, type Score } from "@/lib/api/runs";
import { formatNumber } from "@/lib/format";

/** Human evaluations of the run (all evaluators) + the current user's form (evaluator+). */
export function HumanEvaluationsSection({ run, scores, names }: { run: RunDetail; scores: Score[]; names: Map<string, string> }) {
  const { user, hasRole } = useCurrentUser();
  const canEvaluate = hasRole("evaluator");
  const list = useHumanEvaluations(run.id);
  const catalog = useCriteriaCatalog(canEvaluate);
  const [blind, setBlind] = React.useState(true);

  const rows = list.data ?? [];
  const groups = groupByEvaluator(rows);
  const mine = rows.filter((r) => r.user_id === user?.id);
  const criteria = reviewCriteriaFor(scores, catalog.data);
  const evaluable = run.status === "completed" || run.status === "failed";

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Évaluations humaines</CardTitle>
          <CardDescription>Elles s&apos;appliquent à tous les rounds et alimentent la calibration des juges.</CardDescription>
        </CardHeader>
        <CardContent>
          {list.isPending ? (
            <Skeleton className="h-24 w-full" />
          ) : list.isError ? (
            <ErrorState error={list.error} onRetry={() => void list.refetch()} size="sm" />
          ) : groups.length === 0 ? (
            <EmptyState size="sm" variant="plain" icon={<UserRound />} title="Aucune évaluation humaine" description="Personne n'a encore noté ce run." />
          ) : (
            <ul className="grid gap-3">
              {groups.map((g) => (
                <li key={g.key} className="rounded-lg border border-border p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <UserAvatar user={{ full_name: g.userName }} size="sm" showName />
                    <span className="text-xs text-muted-foreground">
                      <RelativeTime date={g.createdAt} />
                    </span>
                  </div>
                  <ul className="grid gap-2">
                    {g.items.map((e) => (
                      <li key={e.id} className="grid gap-0.5">
                        <div className="flex items-center justify-between gap-2 text-[13px]">
                          <span className="truncate">{names.get(e.criterion_key) ?? e.criterion_key}</span>
                          <span className="flex items-center gap-2">
                            <span className="font-semibold tabular-nums">
                              {formatNumber(e.score, 1)}
                              <span className="text-xs font-normal text-muted-foreground"> / {formatNumber(e.scale_max)}</span>
                            </span>
                            <ScoreBar value={e.normalized_score} showValue={false} widthClassName="w-14" />
                          </span>
                        </div>
                        {e.redacted ? (
                          <RedactedNotice variant="inline" title="Commentaire masqué" />
                        ) : e.explanation ? (
                          <p className="text-xs leading-relaxed text-muted-foreground">{e.explanation}</p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <RequireRole
        min="evaluator"
        fallback={
          <Card>
            <CardContent className="pt-5">
              <EmptyState size="sm" variant="plain" icon={<ClipboardCheck />} title="Évaluation réservée" description="Le rôle évaluateur est nécessaire pour noter un run." />
            </CardContent>
          </Card>
        }
      >
        <Card>
          <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 pb-2">
            <div className="grid gap-1">
              <CardTitle>{mine.length ? "Votre évaluation" : "Évaluer ce run"}</CardTitle>
              <CardDescription>Notez chaque critère sur son échelle ; seuls les critères notés sont envoyés.</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Switch id="human-blind" checked={blind} onCheckedChange={setBlind} size="sm" />
              <Label htmlFor="human-blind" className="flex items-center gap-1 text-xs">
                <EyeOff className="size-3.5" aria-hidden />
                Mode aveugle
              </Label>
            </div>
          </CardHeader>
          <CardContent>
            {run.redacted ? (
              <RedactedNotice description="Le contenu de ce scénario privé vous est masqué : l'évaluation humaine est réservée aux mainteneurs." />
            ) : !evaluable ? (
              <p className="text-[13px] text-muted-foreground">
                {isRunActive(run.status) ? "Le run doit être terminé pour être évalué." : "Les runs annulés ne peuvent pas être évalués."}
              </p>
            ) : catalog.isPending ? (
              <Skeleton className="h-40 w-full" />
            ) : (
              <HumanEvaluationForm runId={run.id} criteria={criteria} existing={mine} aiScores={aiScoresFrom(scores)} blind={blind} />
            )}
          </CardContent>
        </Card>
      </RequireRole>
    </div>
  );
}
