"use client";

import * as React from "react";
import Link from "next/link";
import { Archive, ArchiveRestore, FlaskConical, Layers, Pencil, Pin, Play } from "lucide-react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { KpiCard } from "@/components/domain/kpi-card";
import { CostDisplay } from "@/components/domain/metric-display";
import { ExecutionStatusBadge } from "@/components/domain/status-badge";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
import { useBreadcrumbLabel } from "@/components/layout/shell-context";
import { FeedbackReportById } from "@/components/experiments/feedback-report";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  isActiveExecution,
  useBenchmark,
  useBenchmarkExecutions,
  useExecution,
  useRunBenchmark,
  useUpdateBenchmark,
  type BenchmarkDetail,
  type ExecutionDetail,
} from "@/lib/api/benchmarks";
import { errorMessage } from "@/lib/api/client";
import { scenarioCategoryLabel } from "@/lib/enums";
import { formatDateTime, formatNumber, formatPercent, formatScore100, plural } from "@/lib/format";
import { BenchmarkFormDialog } from "./benchmark-form-dialog";
import { BackLink, DetailSkeleton, HashChip, MetaItem, RunsProgress } from "./common";
import { ExecutionsCard } from "./executions-card";
import { GroupResults } from "./group-results";
import { AgentsRadarCard, GeneralisationCard, Leaderboard } from "./leaderboard";
import { MatrixHeatmap } from "./matrix-heatmap";
import { useUrlState } from "./use-url-state";

const TABS = ["leaderboard", "matrix", "groups", "feedback"] as const;
type Tab = (typeof TABS)[number];

function ConfigSummary({ benchmark }: { benchmark: BenchmarkDetail }) {
  const scenarios = [...benchmark.scenarios].sort((a, b) => a.position - b.position);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Configuration</CardTitle>
        <CardDescription>{benchmark.description || "Aucune description."}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <MetaItem label="Scénarios">{benchmark.n_scenarios}</MetaItem>
          <MetaItem label="Versions d'agents">{benchmark.agents.length}</MetaItem>
          <MetaItem label="Répétitions">{benchmark.repetitions}</MetaItem>
          <MetaItem label="Configuration">
            <Link href={`/evaluation-configs/${benchmark.evaluation_config_id}`} className="text-primary hover:underline">
              {benchmark.evaluation_config_name ?? "Voir"}
            </Link>
          </MetaItem>
        </dl>
        {benchmark.hidden_scenarios ? (
          <Alert tone="amber">
            {plural(benchmark.hidden_scenarios, "scénario")} au-dessus de votre habilitation ne sont pas affichés.
          </Alert>
        ) : null}
        <div className="grid gap-2">
          <p className="text-[11.5px] font-medium uppercase tracking-wide text-subtle-foreground">Versions d&apos;agents</p>
          <ul className="flex flex-wrap gap-2">
            {benchmark.agents.map((a) => (
              <li key={a.agent_version_id} className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-[13px]">
                <Link href={`/agents/${a.agent_id}`} className="font-medium hover:underline">
                  {a.label}
                </Link>
                <HashChip hash={a.content_hash} />
              </li>
            ))}
          </ul>
        </div>
        <div className="grid gap-2">
          <p className="text-[11.5px] font-medium uppercase tracking-wide text-subtle-foreground">Scénarios</p>
          <ul className="grid gap-1 sm:grid-cols-2">
            {scenarios.map((s) => (
              <li key={s.scenario_id} className="flex items-center gap-2 rounded-md px-1 py-0.5 text-[13px]">
                <VisibilityBadge visibility={s.visibility} iconOnly />
                <Link href={`/scenarios/${s.scenario_id}`} className="min-w-0 flex-1 truncate hover:underline">
                  {s.name}
                </Link>
                <span className="hidden text-xs text-muted-foreground lg:inline">{scenarioCategoryLabel(s.category)}</span>
                <ClassificationBadge level={s.classification} showLabel={false} />
                {s.scenario_version_id ? (
                  <Badge tone="violet" icon={<Pin aria-hidden />}>
                    v{s.pinned_version}
                  </Badge>
                ) : (
                  <Badge variant="outline">v{s.latest_version} (dernière)</Badge>
                )}
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}

function ExecutionKpis({ execution }: { execution: ExecutionDetail }) {
  const s = execution.summary;
  const leader = s?.agents.find((a) => a.rank === 1);
  const totalCost = s?.agents.reduce((acc, a) => acc + (a.cost.total ?? 0), 0);
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <KpiCard
        label="Meilleure version"
        value={leader ? formatScore100(leader.composite.mean) : "—"}
        unit="/ 100"
        hint={leader?.agent_label ?? "En attente de l'agrégation"}
        icon={<Layers />}
      />
      <KpiCard
        label="Runs évalués"
        value={formatNumber(s?.totals.n_scored ?? execution.completed_runs, 0)}
        unit={`/ ${formatNumber(execution.total_runs, 0)}`}
        hint={`${execution.n_scenarios} scénarios × ${execution.n_agents} versions × ${execution.repetitions} rép.`}
        icon={<Play />}
        tone="blue"
      />
      <KpiCard
        label="Taux de réussite (leader)"
        value={formatPercent(leader?.pass_rate)}
        hint={leader ? `Garde-fous en échec : ${formatPercent(leader.gate_failure_rate)}` : "—"}
        icon={<FlaskConical />}
        tone="green"
      />
      <KpiCard
        label="Coût total"
        value={<CostDisplay value={totalCost ?? null} />}
        hint={s ? `Généré le ${formatDateTime(s.generated_at)}` : "Calculé à la fin de l'exécution"}
        icon={<Layers />}
        tone="amber"
      />
    </div>
  );
}

function ExecutionResults({ benchmark, executionId }: { benchmark: BenchmarkDetail; executionId: string }) {
  const { get, set } = useUrlState();
  const exec = useExecution(executionId);
  const rawTab = get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(rawTab ?? "") ? (rawTab as Tab) : "leaderboard";
  const [feedbackAgent, setFeedbackAgent] = React.useState<string | null>(null);

  if (exec.isPending) return <Skeleton className="h-96" />;
  if (exec.isError) return <ErrorState error={exec.error} onRetry={() => void exec.refetch()} />;
  const execution = exec.data;
  const summary = execution.summary;
  const active = isActiveExecution(execution.status);
  const classifications = benchmark.scenarios.map((s) => s.classification);
  const reports = summary?.feedback_reports ?? {};
  const reportAgents = summary ? [...summary.agents].sort((a, b) => a.rank - b.rank).filter((a) => reports[a.agent_version_id]) : [];
  const currentFeedbackAgent = feedbackAgent ?? reportAgents[0]?.agent_version_id ?? null;

  return (
    <section aria-labelledby="results-title" className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="results-title" className="text-base font-semibold tracking-tight">
          Résultats de l&apos;exécution n° {execution.number}
        </h2>
        <ExecutionStatusBadge status={execution.status} detail={execution.error} />
        {active ? (
          <RunsProgress className="w-64" completed={execution.completed_runs} failed={execution.failed_runs} total={execution.total_runs} active />
        ) : null}
      </div>
      {execution.error ? <Alert tone="red" title="Erreur d'exécution">{execution.error}</Alert> : null}
      {summary?.restricted ? (
        <Alert tone="amber">
          Résumé limité aux scénarios de votre habilitation ({plural(summary.hidden_scenarios, "scénario masqué", "scénarios masqués")}).
        </Alert>
      ) : null}
      <ExecutionKpis execution={execution} />

      <Tabs value={tab} onValueChange={(v) => set({ tab: v === "leaderboard" ? null : v })}>
        <TabsList>
          <TabsTrigger value="leaderboard">Classement</TabsTrigger>
          <TabsTrigger value="matrix">Matrice</TabsTrigger>
          <TabsTrigger value="groups">Regroupements</TabsTrigger>
          <TabsTrigger value="feedback">Feedback</TabsTrigger>
        </TabsList>

        {!summary && tab !== "groups" ? (
          <TabsContent value={tab}>
            <EmptyState
              icon={<Layers />}
              title={active ? "Exécution en cours" : "Résumé indisponible"}
              description={
                active
                  ? "Le classement, la matrice et les rapports de feedback sont calculés quand tous les runs sont terminés. L'onglet « Regroupements » affiche déjà des résultats provisoires."
                  : "Cette exécution n'a pas produit de résumé agrégé."
              }
              action={
                <Button size="sm" variant="secondary" onClick={() => set({ tab: "groups" })}>
                  Voir les résultats provisoires
                </Button>
              }
            />
          </TabsContent>
        ) : null}

        {summary ? (
          <>
            <TabsContent value="leaderboard" className="grid gap-4">
              <Leaderboard summary={summary} />
              <div className="grid gap-4 xl:grid-cols-2">
                <AgentsRadarCard summary={summary} />
                <GeneralisationCard summary={summary} />
              </div>
            </TabsContent>
            <TabsContent value="matrix">
              <MatrixHeatmap matrix={summary.matrix} executionId={execution.id} classifications={classifications} />
            </TabsContent>
            <TabsContent value="feedback">
              <Card>
                <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
                  <div className="grid gap-1">
                    <CardTitle>Rapports de feedback par version</CardTitle>
                    <CardDescription>Forces, faiblesses, erreurs et recommandations agrégées sur les runs de l&apos;exécution.</CardDescription>
                  </div>
                  {reportAgents.length ? (
                    <SimpleSelect
                      size="sm"
                      className="w-64"
                      aria-label="Version d'agent"
                      value={currentFeedbackAgent ?? undefined}
                      options={reportAgents.map((a) => ({ value: a.agent_version_id, label: a.agent_label }))}
                      onValueChange={setFeedbackAgent}
                    />
                  ) : null}
                </CardHeader>
                <CardContent>
                  {currentFeedbackAgent ? (
                    <FeedbackReportById id={reports[currentFeedbackAgent]} />
                  ) : (
                    <p className="text-[13px] text-muted-foreground">Aucun rapport de feedback pour cette exécution.</p>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </>
        ) : null}
        <TabsContent value="groups">
          <GroupResults benchmarkId={benchmark.id} executionId={execution.id} live={active} />
        </TabsContent>
      </Tabs>
    </section>
  );
}

export function BenchmarkDetailView({ id }: { id: string }) {
  const { get, set } = useUrlState();
  const query = useBenchmark(id);
  const executions = useBenchmarkExecutions(id, { page: 1, page_size: 10 });
  const run = useRunBenchmark(id);
  const update = useUpdateBenchmark(id);
  const [editOpen, setEditOpen] = React.useState(false);
  const [launchOpen, setLaunchOpen] = React.useState(false);
  useBreadcrumbLabel(id, query.data?.name);

  const latest = executions.data?.items[0];
  const selectedId = get("execution") ?? latest?.id ?? null;

  if (query.isPending) return <DetailSkeleton />;
  if (query.isError)
    return (
      <>
        <BackLink href="/benchmarks">Benchmarks</BackLink>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </>
    );
  const b = query.data;
  const runCount = b.n_scenarios * b.agents.length * b.repetitions;
  const levels = b.scenarios.map((s) => s.classification);

  return (
    <>
      <BackLink href="/benchmarks">Benchmarks</BackLink>
      <PageHeader
        eyebrow="Benchmark"
        title={b.name}
        icon={<Layers />}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs">{b.slug}</span>
            {b.tags.map((t) => (
              <Badge key={t} variant="outline">
                {t}
              </Badge>
            ))}
          </span>
        }
        meta={b.archived ? <Badge tone="neutral">Archivé</Badge> : null}
        actions={
          <RequireRole min="editor">
            <Button
              variant="ghost"
              size="sm"
              leftIcon={b.archived ? <ArchiveRestore aria-hidden /> : <Archive aria-hidden />}
              loading={update.isPending}
              onClick={() => update.mutate({ archived: !b.archived }, { onError: (e) => toast.error(errorMessage(e)) })}
            >
              {b.archived ? "Désarchiver" : "Archiver"}
            </Button>
            <Button variant="secondary" size="sm" leftIcon={<Pencil aria-hidden />} onClick={() => setEditOpen(true)}>
              Modifier
            </Button>
            <Button asChild variant="secondary" size="sm">
              <Link href={`/experiments?new=1&benchmark=${b.id}`}>
                <FlaskConical aria-hidden /> Expérience
              </Link>
            </Button>
            <Button size="sm" leftIcon={<Play aria-hidden />} onClick={() => setLaunchOpen(true)} disabled={b.archived}>
              Lancer · {formatNumber(runCount, 0)} runs
            </Button>
          </RequireRole>
        }
      />
      <div className="grid gap-6">
        <ClassificationBanner levels={levels} context="comparison" />
        <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <ConfigSummary benchmark={b} />
          <ExecutionsCard
            benchmarkId={b.id}
            selectedId={selectedId}
            onSelect={(eid) => set({ execution: eid === latest?.id ? null : eid })}
            onLaunch={() => setLaunchOpen(true)}
          />
        </div>
        {selectedId ? <ExecutionResults benchmark={b} executionId={selectedId} /> : null}
      </div>

      <BenchmarkFormDialog open={editOpen} onOpenChange={setEditOpen} benchmark={b} />
      <ConfirmDialog
        open={launchOpen}
        onOpenChange={setLaunchOpen}
        title="Lancer le benchmark ?"
        description={`${b.n_scenarios} scénario(s) × ${b.agents.length} version(s) d'agent × ${b.repetitions} répétition(s) = ${formatNumber(runCount, 0)} runs, évalués avec ${b.evaluation_config_name ?? "la configuration du benchmark"}.`}
        confirmLabel={`Lancer ${formatNumber(runCount, 0)} runs`}
        onConfirm={async () => {
          try {
            const ex = await run.mutateAsync();
            toast.success(`Exécution n° ${ex.number} lancée (${formatNumber(ex.total_runs, 0)} runs)`);
            set({ execution: null, tab: null });
            setLaunchOpen(false);
          } catch (error) {
            toast.error(errorMessage(error));
          }
        }}
      />
    </>
  );
}
