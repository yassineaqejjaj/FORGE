"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ExternalLink, EyeOff, SkipForward } from "lucide-react";
import { toast } from "sonner";

import { RoleGate } from "@/components/auth/require-role";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { ScoreGauge } from "@/components/domain/score-gauge";
import { FinalOutput } from "@/components/runs/detail/final-output";
import { ScenarioPanel } from "@/components/runs/detail/scenario-panel";
import { useSearchState } from "@/components/runs/use-search-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useCurrentUser } from "@/hooks/use-current-user";
import { errorMessage } from "@/lib/api/client";
import { reviewsApi, useCriteriaCatalog, useHumanEvaluations } from "@/lib/api/reviews";
import { readTraceSummary, useRun, useRunScores } from "@/lib/api/runs";
import { HumanEvaluationForm } from "./human-evaluation-form";
import { aiScoresFrom, reviewCriteriaFor } from "./review-criteria";

/** `/reviews/[runId]` — review workspace: what the agent received, what it answered, the criteria form. */
export function ReviewWorkspaceView({ runId }: { runId: string }) {
  const router = useRouter();
  const search = useSearchState();
  const { user } = useCurrentUser();
  const blind = search.get("blind") !== "0";
  const datasetId = search.get("dataset");

  const run = useRun(runId);
  const scores = useRunScores(runId, null, { enabled: Boolean(run.data) });
  const catalog = useCriteriaCatalog();
  const human = useHumanEvaluations(runId);
  const [submitted, setSubmitted] = React.useState(false);
  const [nextLoading, setNextLoading] = React.useState(false);

  React.useEffect(() => setSubmitted(false), [runId]);

  const filterQs = React.useMemo(() => {
    const qs = new URLSearchParams();
    if (!blind) qs.set("blind", "0");
    if (datasetId) qs.set("dataset", datasetId);
    const s = qs.toString();
    return s ? `?${s}` : "";
  }, [blind, datasetId]);
  const backHref = `/reviews${filterQs}`;

  const goNext = async () => {
    setNextLoading(true);
    try {
      const page = await reviewsApi.queue({ page: 1, page_size: 5, dataset_id: datasetId, blind });
      const next = page.items.find((i) => i.run_id !== runId);
      if (!next) {
        toast.success("File de revue terminée. Merci !");
        router.push(backHref);
        return;
      }
      router.push(`/reviews/${next.run_id}${filterQs}`);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setNextLoading(false);
    }
  };

  const mine = (human.data ?? []).filter((e) => e.user_id === user?.id);
  const criteria = reviewCriteriaFor(scores.data?.scores, catalog.data);
  const showAi = !blind || submitted;

  return (
    <RoleGate min="evaluator">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <Button asChild variant="ghost" size="sm">
          <Link href={backHref}>
            <ArrowLeft aria-hidden />
            File de revue
          </Link>
        </Button>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Switch id="workspace-blind" size="sm" checked={blind} onCheckedChange={(v) => search.set({ blind: v ? undefined : "0" })} />
            <Label htmlFor="workspace-blind" className="flex items-center gap-1 text-xs">
              <EyeOff className="size-3.5" aria-hidden />
              Mode aveugle
            </Label>
          </div>
          <Button variant="secondary" size="sm" onClick={() => void goNext()} loading={nextLoading} leftIcon={<SkipForward aria-hidden />}>
            {submitted ? "Item suivant" : "Passer"}
          </Button>
        </div>
      </div>

      {run.isPending ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <Skeleton className="h-[32rem] w-full rounded-xl" />
          <Skeleton className="h-[32rem] w-full rounded-xl" />
        </div>
      ) : run.isError ? (
        <ErrorState error={run.error} onRetry={() => void run.refetch()} />
      ) : (
        <>
          <ClassificationBanner level={run.data.scenario.classification} context="run" className="mb-4" />
          <header className="mb-4 flex flex-wrap items-start justify-between gap-4 rounded-xl border border-border bg-card p-4 shadow-xs">
            <div className="grid min-w-0 gap-1">
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle-foreground">Revue humaine</p>
              <h1 className="text-xl font-semibold tracking-tight">{run.data.scenario.name}</h1>
              <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                {String((run.data.agent as Record<string, unknown>).label ?? "")}
                <Link href={`/runs/${runId}`} className="inline-flex items-center gap-1 text-xs text-primary hover:underline" target="_blank" rel="noopener noreferrer">
                  Voir le run complet
                  <ExternalLink className="size-3" aria-hidden />
                </Link>
              </p>
            </div>
            {showAi ? (
              <ScoreGauge value={run.data.composite_score} size="sm" label="IA" passed={run.data.passed} gateFailed={run.data.gate_failed} />
            ) : (
              <Badge tone="violet" icon={<EyeOff aria-hidden />} size="md">
                Score IA masqué
              </Badge>
            )}
          </header>

          {run.data.redacted ? (
            <RedactedNotice description="Le contenu de ce scénario privé vous est masqué : l'évaluation humaine est réservée aux mainteneurs." />
          ) : (
            <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
              <div className="grid gap-4">
                <ScenarioPanel run={run.data} compact />
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle>Réponse de l&apos;agent</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <FinalOutput trace={readTraceSummary(run.data.trace)} redacted={run.data.redacted} collapsible={false} />
                  </CardContent>
                </Card>
              </div>
              <Card className="lg:sticky lg:top-20">
                <CardHeader className="pb-2">
                  <CardTitle>Votre évaluation</CardTitle>
                  <CardDescription>Notez chaque critère sur son échelle, en vous appuyant sur la question et la grille.</CardDescription>
                </CardHeader>
                <CardContent>
                  {scores.isPending || catalog.isPending || human.isPending ? (
                    <Skeleton className="h-96 w-full" />
                  ) : (
                    <HumanEvaluationForm
                      runId={runId}
                      criteria={criteria}
                      existing={mine}
                      aiScores={aiScoresFrom(scores.data?.scores)}
                      blind={blind}
                      onSubmitted={() => setSubmitted(true)}
                      afterSubmit={
                        <Button variant="secondary" onClick={() => void goNext()} loading={nextLoading} rightIcon={<SkipForward aria-hidden />}>
                          Item suivant
                        </Button>
                      }
                    />
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </>
      )}
    </RoleGate>
  );
}
