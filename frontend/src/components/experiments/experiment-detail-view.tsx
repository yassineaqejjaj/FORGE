"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Ban, FileText, FlaskConical, GitBranchPlus, Lightbulb, Play } from "lucide-react";

import { RequireRole } from "@/components/auth/require-role";
import { BackLink, DetailSkeleton, HashChip, MetaItem, RunsProgress } from "@/components/benchmarks/common";
import { useUrlState } from "@/components/benchmarks/use-url-state";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { ExecutionStatusBadge } from "@/components/domain/status-badge";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
import { useBreadcrumbLabel } from "@/components/layout/shell-context";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { isActiveExecution } from "@/lib/api/benchmarks";
import { useCancelExperiment, useComparison, useExperiment, type ExperimentDetail } from "@/lib/api/experiments";
import { formatDateTime, plural } from "@/lib/format";
import { ArmsCard, CriterionComparisonCard, DimensionComparisonCard, ErrorChangesCard, RecommendationHero, ResourcesCard, StatisticsNote } from "./comparison-sections";
import { FeedbackReportById } from "./feedback-report";
import { GateCard } from "./gate-card";
import { ScenarioChangesSection } from "./scenario-changes";

const TABS = ["summary", "scenarios", "errors", "gate", "feedback"] as const;
type Tab = (typeof TABS)[number];

function ExperimentInfo({ x }: { x: ExperimentDetail }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Protocole</CardTitle>
        {x.hypothesis ? <CardDescription>Hypothèse : {x.hypothesis}</CardDescription> : null}
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid items-center gap-3 md:grid-cols-[1fr_auto_1fr]">
          <div className="grid gap-1 rounded-lg border border-border p-3">
            <span className="text-[11.5px] font-medium uppercase tracking-wide text-subtle-foreground">Baseline</span>
            {x.baseline ? (
              <>
                <Link href={`/agents/${x.baseline.agent_id}`} className="font-medium hover:underline">
                  {x.baseline.label}
                </Link>
                <HashChip hash={x.baseline.content_hash} />
              </>
            ) : (
              "—"
            )}
          </div>
          <ArrowRight className="hidden size-4 text-muted-foreground md:block" aria-hidden />
          <div className="grid gap-1 rounded-lg border border-brand/40 bg-brand-soft/30 p-3">
            <span className="text-[11.5px] font-medium uppercase tracking-wide text-subtle-foreground">Candidate</span>
            {x.candidate ? (
              <>
                <Link href={`/agents/${x.candidate.agent_id}`} className="font-medium hover:underline">
                  {x.candidate.label}
                </Link>
                <HashChip hash={x.candidate.content_hash} />
              </>
            ) : (
              "—"
            )}
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <MetaItem label="Source">
            {x.benchmark_id ? (
              <Link href={`/benchmarks/${x.benchmark_id}`} className="text-primary hover:underline">
                {x.benchmark_name ?? "Benchmark"}
              </Link>
            ) : (
              "Liste de scénarios"
            )}
          </MetaItem>
          <MetaItem label="Scénarios × répétitions">
            {x.n_scenarios} × {x.repetitions} × 2 bras
          </MetaItem>
          <MetaItem label="Configuration">
            <Link href={`/evaluation-configs/${x.evaluation_config_id}`} className="text-primary hover:underline">
              Voir la configuration
            </Link>
          </MetaItem>
          <MetaItem label="Lancée">
            {formatDateTime(x.started_at ?? x.created_at)} <span className="text-muted-foreground">({x.trigger})</span>
          </MetaItem>
        </dl>
        {x.description ? <p className="text-[13px] text-muted-foreground">{x.description}</p> : null}
        {x.scenarios.length ? (
          <details className="group">
            <summary className="cursor-pointer text-[13px] font-medium text-muted-foreground hover:text-foreground">
              {plural(x.scenarios.length, "version de scénario épinglée", "versions de scénarios épinglées")}
            </summary>
            <ul className="mt-2 grid gap-1 sm:grid-cols-2">
              {x.scenarios.map((s) => (
                <li key={s.scenario_version_id} className="flex items-center gap-2 text-[13px]">
                  <VisibilityBadge visibility={s.visibility} iconOnly />
                  <Link href={`/scenarios/${s.scenario_id}`} className="truncate hover:underline">
                    {s.name}
                  </Link>
                  <Badge variant="outline">v{s.version}</Badge>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ImprovementLoop({ x }: { x: ExperimentDetail }) {
  const candidateAgent = x.candidate?.agent_id;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Lightbulb className="size-4 text-amber-500" aria-hidden />
          Boucle d&apos;amélioration
        </CardTitle>
        <CardDescription>
          Utilisez le rapport de feedback de l&apos;expérience pour produire la prochaine version candidate, puis relancez une
          expérience contre la même baseline.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        {candidateAgent ? (
          <RequireRole min="editor">
            <Button asChild size="sm">
              <Link href={`/agents/${candidateAgent}/versions/new?base=${x.candidate_version_id}`}>
                <GitBranchPlus aria-hidden /> Créer une version candidate à partir du feedback
              </Link>
            </Button>
          </RequireRole>
        ) : null}
        <RequireRole min="editor">
          <Button asChild size="sm" variant="secondary">
            <Link
              href={`/experiments?new=1&baseline=${x.baseline_version_id}${x.benchmark_id ? `&benchmark=${x.benchmark_id}` : ""}`}
            >
              <FlaskConical aria-hidden /> Nouvelle expérience contre la baseline
            </Link>
          </Button>
        </RequireRole>
      </CardContent>
    </Card>
  );
}

export function ExperimentDetailView({ id }: { id: string }) {
  const { get, set } = useUrlState();
  const query = useExperiment(id);
  const active = isActiveExecution(query.data?.status);
  const comparison = useComparison(id, { enabled: query.isSuccess, live: active });
  const cancel = useCancelExperiment();
  const [cancelOpen, setCancelOpen] = React.useState(false);
  useBreadcrumbLabel(id, query.data?.name);
  const status = query.data?.status;
  const refetchComparison = comparison.refetch;
  React.useEffect(() => {
    // Final (non-provisional) comparison as soon as the experiment leaves the active states.
    if (status && !isActiveExecution(status)) void refetchComparison();
  }, [status, refetchComparison]);
  const rawTab = get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(rawTab ?? "") ? (rawTab as Tab) : "summary";

  if (query.isPending) return <DetailSkeleton />;
  if (query.isError)
    return (
      <>
        <BackLink href="/experiments">Expériences</BackLink>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </>
    );
  const x = query.data;
  const c = comparison.data;

  return (
    <>
      <BackLink href="/experiments">Expériences</BackLink>
      <PageHeader
        eyebrow="Expérience"
        title={x.name}
        icon={<FlaskConical />}
        meta={<ExecutionStatusBadge status={x.status} size="md" detail={x.error} />}
        description={
          x.baseline && x.candidate ? (
            <span className="inline-flex flex-wrap items-center gap-1.5">
              {x.baseline.label} <ArrowRight className="size-3.5" aria-hidden /> <span className="font-medium text-foreground">{x.candidate.label}</span>
            </span>
          ) : undefined
        }
        actions={
          <>
            <Button asChild variant="secondary" size="sm">
              <Link href={`/runs?experiment_id=${x.id}`}>
                <Play aria-hidden /> Runs
              </Link>
            </Button>
            {active ? (
              <RequireRole min="editor">
                <Button variant="destructive-outline" size="sm" leftIcon={<Ban aria-hidden />} onClick={() => setCancelOpen(true)}>
                  Annuler
                </Button>
              </RequireRole>
            ) : null}
          </>
        }
      />

      <div className="grid gap-5">
        <ClassificationBanner levels={x.scenarios.map((s) => s.classification)} context="comparison" />
        {x.warnings?.length ? (
          <Alert tone="amber" title="Avertissements">
            <ul className="grid gap-0.5">
              {(x.warnings ?? []).map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </Alert>
        ) : null}
        {x.error ? <Alert tone="red" title="Erreur">{x.error}</Alert> : null}
        {x.hidden_scenarios ? (
          <Alert tone="amber">
            {plural(x.hidden_scenarios, "scénario")} au-dessus de votre habilitation : la comparaison affichée est restreinte.
          </Alert>
        ) : null}
        {active ? (
          <Card>
            <CardContent className="flex flex-wrap items-center gap-4 pt-5">
              <div className="grid gap-1">
                <p className="text-[13px] font-medium">Expérience en cours</p>
                <p className="text-xs text-muted-foreground">
                  Les résultats ci-dessous sont provisoires et se mettent à jour automatiquement.
                </p>
              </div>
              <RunsProgress className="w-full max-w-md flex-1" completed={x.completed_runs} failed={x.failed_runs} total={x.total_runs} active />
            </CardContent>
          </Card>
        ) : null}

        {comparison.isPending ? (
          <Skeleton className="h-56" />
        ) : comparison.isError ? (
          <ErrorState error={comparison.error} onRetry={() => void comparison.refetch()} title="Comparaison indisponible" />
        ) : c ? (
          <RecommendationHero comparison={c} />
        ) : null}

        <Tabs value={tab} onValueChange={(v) => set({ tab: v === "summary" ? null : v })}>
          <TabsList>
            <TabsTrigger value="summary">Synthèse</TabsTrigger>
            <TabsTrigger value="scenarios" count={c ? c.regressions.length : undefined}>
              Régressions &amp; scénarios
            </TabsTrigger>
            <TabsTrigger value="errors">Erreurs</TabsTrigger>
            <TabsTrigger value="gate">Garde-fou CI</TabsTrigger>
            <TabsTrigger value="feedback">Feedback</TabsTrigger>
          </TabsList>

          <TabsContent value="summary" className="grid gap-4">
            {c ? (
              <>
                <DimensionComparisonCard comparison={c} />
                <CriterionComparisonCard comparison={c} />
                <ResourcesCard comparison={c} />
                <ArmsCard comparison={c} />
                <StatisticsNote comparison={c} />
              </>
            ) : null}
            <ExperimentInfo x={x} />
          </TabsContent>
          <TabsContent value="scenarios">
            {c ? (
              <ScenarioChangesSection
                experimentId={x.id}
                regressions={c.regressions}
                improvements={c.improvements}
                scenarios={c.scenarios}
                baselineLabel={c.baseline.agent_label}
                candidateLabel={c.candidate.agent_label}
              />
            ) : (
              <EmptyState title="Comparaison indisponible" icon={<FlaskConical />} />
            )}
          </TabsContent>
          <TabsContent value="errors">{c ? <ErrorChangesCard comparison={c} /> : null}</TabsContent>
          <TabsContent value="gate">
            <GateCard experimentId={x.id} />
          </TabsContent>
          <TabsContent value="feedback" className="grid gap-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FileText className="size-4 text-muted-foreground" aria-hidden />
                  Rapport de feedback de l&apos;expérience
                </CardTitle>
                <CardDescription>Construit sur les runs de la candidate ; format JSON consommable par NOVA.</CardDescription>
              </CardHeader>
              <CardContent>
                {c?.feedback_report_id ? (
                  <FeedbackReportById id={c.feedback_report_id} />
                ) : (
                  <p className="text-[13px] text-muted-foreground">
                    {active ? "Le rapport est généré à la fin de l'expérience." : "Aucun rapport de feedback pour cette expérience."}
                  </p>
                )}
              </CardContent>
            </Card>
            <ImprovementLoop x={x} />
            {x.source_feedback_report_id ? (
              <Card>
                <CardHeader>
                  <CardTitle>Rapport source</CardTitle>
                  <CardDescription>Le feedback qui a motivé cette version candidate (boucle d&apos;amélioration).</CardDescription>
                </CardHeader>
                <CardContent>
                  <FeedbackReportById id={x.source_feedback_report_id} />
                </CardContent>
              </Card>
            ) : null}
          </TabsContent>
        </Tabs>
      </div>

      <ConfirmDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title="Annuler l'expérience ?"
        description="Les runs en attente sont annulés ; la comparaison est calculée sur les runs déjà terminés."
        confirmLabel="Annuler l'expérience"
        cancelLabel="Continuer"
        destructive
        onConfirm={async () => {
          try {
            await cancel.mutateAsync(x.id);
            setCancelOpen(false);
          } catch {
            // error toast shown by the mutation cache
          }
        }}
      />
    </>
  );
}
