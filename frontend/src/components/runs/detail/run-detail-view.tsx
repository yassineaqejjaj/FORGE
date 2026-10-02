"use client";

import * as React from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bug, ClipboardCheck, Gavel, Lightbulb, Ruler } from "lucide-react";

import { useShell } from "@/components/layout/shell-context";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMediaQuery } from "@/hooks/use-media-query";
import { queryKeys } from "@/lib/api/query-keys";
import {
  isRunActive,
  readMessages,
  readModelCalls,
  readToolCalls,
  readTraceEvents,
  readTraceSummary,
  useRun,
  useRunErrors,
  useRunEvaluations,
  useRunFeedback,
  useRunScores,
  useRunTimeline,
  useRunTrace,
  type RunDetail,
} from "@/lib/api/runs";
import { truncate } from "@/lib/format";
import { useSearchState } from "../use-search-state";
import { ErrorsSection, FeedbackSection } from "./errors-feedback";
import { EventDrawer } from "./event-drawer";
import { JudgeEvaluationsSection, RuleResultsSection } from "./evaluation-sections";
import { FinalOutput } from "./final-output";
import { HumanEvaluationsSection } from "./human-evaluations-section";
import { ProvenanceSheet } from "./provenance-sheet";
import { RunDetailProvider, useRunDetail, type RunDetailContextValue } from "./run-detail-context";
import { RunHeader } from "./run-header";
import { ScenarioPanel } from "./scenario-panel";
import { ScorePanel } from "./score-panel";
import { ModelCallsPanel, MessagesPanel, ToolCallsPanel } from "./trace-panels";
import { TraceTimeline } from "./trace-timeline";

type ColumnTab = "scenario" | "execution" | "scores";
type SectionTab = "judges" | "rules" | "errors" | "feedback" | "human";
const SECTION_TABS: readonly SectionTab[] = ["judges", "rules", "errors", "feedback", "human"];

function ColumnSkeleton({ blocks = 3 }: { blocks?: number }) {
  return (
    <div className="grid gap-4" aria-hidden>
      {Array.from({ length: blocks }, (_, i) => (
        <Skeleton key={i} className={i === 0 ? "h-40 w-full rounded-xl" : "h-56 w-full rounded-xl"} />
      ))}
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label="Chargement du run">
      <Skeleton className="h-36 w-full rounded-xl" />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)_minmax(0,1fr)]">
        <ColumnSkeleton />
        <ColumnSkeleton />
        <ColumnSkeleton />
      </div>
    </div>
  );
}

function ExecutionColumn({ run, selectedSeq, onOpenEvent }: { run: RunDetail; selectedSeq: number | null; onOpenEvent: (seq: number) => void }) {
  const live = isRunActive(run.status);
  const timeline = useRunTimeline(run.id, { live });
  const trace = useRunTrace(run.id, { live });
  const [tab, setTab] = React.useState("timeline");
  const ctx = useRunDetail();
  const focusNonce = ctx?.focusNonce ?? 0;
  // An evidence link was clicked: bring the timeline back into view.
  React.useEffect(() => {
    if (focusNonce > 0) setTab("timeline");
  }, [focusNonce]);
  const messages = readMessages(trace.data);
  const tools = readToolCalls(trace.data);
  const models = readModelCalls(trace.data);
  const summary = readTraceSummary(trace.data?.trace) ?? readTraceSummary(run.trace);

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Trace d&apos;exécution</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList variant="pills">
              <TabsTrigger value="timeline" count={timeline.data?.items.length}>Timeline</TabsTrigger>
              <TabsTrigger value="messages" count={trace.data ? messages.length : undefined}>Messages</TabsTrigger>
              <TabsTrigger value="tools" count={trace.data ? tools.length : undefined}>Outils</TabsTrigger>
              <TabsTrigger value="models" count={trace.data ? models.length : undefined}>Modèles</TabsTrigger>
            </TabsList>
            <TabsContent value="timeline">
              {timeline.isPending ? (
                <Skeleton className="h-72 w-full" />
              ) : timeline.isError ? (
                <ErrorState error={timeline.error} onRetry={() => void timeline.refetch()} size="sm" />
              ) : timeline.data.items.length === 0 ? (
                <p className="py-6 text-center text-[13px] text-muted-foreground">
                  {live ? "En attente des premiers événements de l'agent…" : "Aucun événement enregistré pour ce run."}
                </p>
              ) : (
                <TraceTimeline timeline={timeline.data} onOpenEvent={onOpenEvent} selectedSeq={selectedSeq} />
              )}
            </TabsContent>
            <TabsContent value="messages">
              {trace.isPending ? <Skeleton className="h-40 w-full" /> : trace.isError ? <ErrorState error={trace.error} size="sm" /> : <MessagesPanel messages={messages} redacted={trace.data.redacted} />}
            </TabsContent>
            <TabsContent value="tools">
              {trace.isPending ? <Skeleton className="h-40 w-full" /> : trace.isError ? <ErrorState error={trace.error} size="sm" /> : <ToolCallsPanel calls={tools} />}
            </TabsContent>
            <TabsContent value="models">
              {trace.isPending ? <Skeleton className="h-40 w-full" /> : trace.isError ? <ErrorState error={trace.error} size="sm" /> : <ModelCallsPanel calls={models} />}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Sortie finale</CardTitle>
        </CardHeader>
        <CardContent>
          <FinalOutput
            trace={summary}
            redacted={run.redacted}
            emptyHint={live ? "La sortie apparaîtra à la fin de l'exécution." : run.error ? "L'exécution a échoué avant de produire une sortie." : undefined}
          />
        </CardContent>
      </Card>

      <EventDrawer
        seq={selectedSeq}
        onSeqChange={(seq) => (seq === null ? onOpenEvent(-1) : onOpenEvent(seq))}
        events={trace.data ? readTraceEvents(trace.data) : undefined}
        items={timeline.data?.items ?? []}
        loading={trace.isPending}
      />
    </div>
  );
}

/** `/runs/[id]` — understand why the agent got its score: scenario | trace & output | scores, then verdicts. */
export function RunDetailView({ id }: { id: string }) {
  const qc = useQueryClient();
  const search = useSearchState();
  const { setCrumbLabel } = useShell();
  const wide = useMediaQuery("(min-width: 1280px)");

  const run = useRun(id);
  const status = run.data?.status;
  const live = isRunActive(status);
  const round = search.getNumber("round") ?? null;
  const enabled = Boolean(run.data);

  const scores = useRunScores(id, round, { live, enabled });
  const evaluations = useRunEvaluations(id, round, { live, enabled });
  const errors = useRunErrors(id, round, { live, enabled });
  const feedback = useRunFeedback(id, round, { live, enabled });
  const timeline = useRunTimeline(id, { live, enabled });

  // Refresh everything once when the run reaches a terminal status.
  const prevStatus = React.useRef(status);
  React.useEffect(() => {
    if (prevStatus.current && isRunActive(prevStatus.current) && status && !isRunActive(status)) {
      void qc.invalidateQueries({ queryKey: queryKeys.detail("runs", id) });
    }
    prevStatus.current = status;
  }, [status, id, qc]);

  React.useEffect(() => {
    if (!run.data) return;
    setCrumbLabel(id, truncate(run.data.scenario.name, 36));
    return () => setCrumbLabel(id, null);
  }, [id, run.data, setCrumbLabel]);

  const [columnTab, setColumnTab] = React.useState<ColumnTab>("scores");
  const [highlightedSeq, setHighlightedSeq] = React.useState<number | null>(null);
  const [focusNonce, setFocusNonce] = React.useState(0);
  const selectedSeq = search.getNumber("event") ?? null;
  const criterionKey = search.get("criterion") ?? null;
  const sectionParam = search.get("section");
  const section: SectionTab = (SECTION_TABS as readonly string[]).includes(sectionParam ?? "") ? (sectionParam as SectionTab) : "judges";

  const items = timeline.data?.items;
  const ctx = React.useMemo<RunDetailContextValue>(
    () => ({
      runId: id,
      round,
      highlightedSeq,
      focusNonce,
      focusEvent: (seq) => {
        setHighlightedSeq(seq);
        setFocusNonce((n) => n + 1);
        if (!wide) setColumnTab("execution");
        if (search.get("criterion")) search.set({ criterion: undefined }, { resetPage: false });
      },
      openEvent: (seq) => search.set({ event: seq, criterion: undefined }, { resetPage: false }),
      openProvenance: (key) => search.set({ criterion: key }, { resetPage: false }),
      eventLabel: (seq) => {
        const it = items?.find((i) => i.seq === seq);
        return it ? `${it.label} — ${it.name}` : undefined;
      },
    }),
    [id, round, highlightedSeq, focusNonce, wide, search, items],
  );

  // Deep link from the errors explorer: ?event_id=<trace event uuid>.
  const eventId = search.get("event_id");
  React.useEffect(() => {
    if (!eventId || !items) return;
    const found = items.find((i) => i.id === eventId);
    search.set({ event_id: undefined, event: found?.seq }, { resetPage: false });
    if (found) {
      setHighlightedSeq(found.seq);
      setFocusNonce((n) => n + 1);
      if (!wide) setColumnTab("execution");
    }
  }, [eventId, items, search, wide]);

  if (run.isPending) return <DetailSkeleton />;
  if (run.isError)
    return (
      <ErrorState
        size="lg"
        error={run.error}
        onRetry={() => void run.refetch()}
        action={
          <Button asChild variant="secondary" size="sm">
            <Link href="/runs">
              <ArrowLeft aria-hidden />
              Retour aux runs
            </Link>
          </Button>
        }
      />
    );

  const data = run.data;
  const names = new Map<string, string>();
  for (const s of scores.data?.scores ?? []) if (s.criterion_name) names.set(s.criterion_key, s.criterion_name);
  const rounds = scores.data?.rounds ?? (data.evaluation_round ? [data.evaluation_round] : []);
  const evalItems = evaluations.data?.items ?? [];
  const errorItems = errors.data?.items ?? [];
  const judgeCount = evalItems.filter((e) => e.evaluator_kind === "llm_judge").length;
  const ruleCount = evalItems.filter((e) => e.evaluator_kind === "rule").length;

  const openEvent = (seq: number) => search.set({ event: seq >= 0 ? seq : undefined }, { resetPage: false });

  const left = <ScenarioPanel run={data} />;
  const centre = <ExecutionColumn run={data} selectedSeq={selectedSeq} onOpenEvent={openEvent} />;
  const right = scores.isPending ? (
    <ColumnSkeleton />
  ) : scores.isError ? (
    <ErrorState error={scores.error} onRetry={() => void scores.refetch()} />
  ) : (
    <ScorePanel run={data} scores={scores.data} />
  );

  return (
    <RunDetailProvider value={ctx}>
      <RunHeader
        run={data}
        rounds={rounds}
        round={round}
        onRoundChange={(r) => search.set({ round: r ?? undefined }, { resetPage: false })}
        onReevaluated={() => search.set({ round: undefined }, { resetPage: false })}
      />

      {wide ? (
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)_minmax(0,1fr)]">
          <section aria-label="Scénario">{left}</section>
          <section aria-label="Exécution">{centre}</section>
          <section aria-label="Scores">{right}</section>
        </div>
      ) : (
        <Tabs value={columnTab} onValueChange={(v) => setColumnTab(v as ColumnTab)}>
          <TabsList className="sticky top-14 z-20 bg-background">
            <TabsTrigger value="scenario">Scénario</TabsTrigger>
            <TabsTrigger value="execution">Exécution</TabsTrigger>
            <TabsTrigger value="scores">Scores</TabsTrigger>
          </TabsList>
          <TabsContent value="scenario">{left}</TabsContent>
          <TabsContent value="execution">{centre}</TabsContent>
          <TabsContent value="scores">{right}</TabsContent>
        </Tabs>
      )}

      <section aria-label="Détail de l'évaluation" className="mt-8">
        <Tabs value={section} onValueChange={(v) => search.set({ section: v === "judges" ? undefined : v }, { resetPage: false })}>
          <TabsList>
            <TabsTrigger value="judges" count={evaluations.data ? judgeCount : undefined}>
              <Gavel aria-hidden />
              Juges
            </TabsTrigger>
            <TabsTrigger value="rules" count={evaluations.data ? ruleCount : undefined}>
              <Ruler aria-hidden />
              Règles et métriques
            </TabsTrigger>
            <TabsTrigger value="errors" count={errors.data ? errorItems.length : undefined}>
              <Bug aria-hidden />
              Erreurs
            </TabsTrigger>
            <TabsTrigger value="feedback">
              <Lightbulb aria-hidden />
              Feedback
            </TabsTrigger>
            <TabsTrigger value="human" count={data.counts.human_evaluations}>
              <ClipboardCheck aria-hidden />
              Évaluations humaines
            </TabsTrigger>
          </TabsList>
          <TabsContent value="judges">
            {evaluations.isPending ? (
              <Skeleton className="h-64 w-full" />
            ) : evaluations.isError ? (
              <ErrorState error={evaluations.error} onRetry={() => void evaluations.refetch()} />
            ) : (
              <JudgeEvaluationsSection run={data} evaluations={evalItems} names={names} />
            )}
          </TabsContent>
          <TabsContent value="rules">
            {evaluations.isPending ? (
              <Skeleton className="h-64 w-full" />
            ) : evaluations.isError ? (
              <ErrorState error={evaluations.error} onRetry={() => void evaluations.refetch()} />
            ) : (
              <RuleResultsSection run={data} evaluations={evalItems} names={names} />
            )}
          </TabsContent>
          <TabsContent value="errors">
            {errors.isPending ? (
              <Skeleton className="h-48 w-full" />
            ) : errors.isError ? (
              <ErrorState error={errors.error} onRetry={() => void errors.refetch()} />
            ) : (
              <ErrorsSection errors={errorItems} names={names} />
            )}
          </TabsContent>
          <TabsContent value="feedback">
            <FeedbackSection
              report={feedback.data}
              loading={feedback.isPending && feedback.fetchStatus === "fetching"}
              error={feedback.error}
              onRetry={() => void feedback.refetch()}
              pending={live}
            />
          </TabsContent>
          <TabsContent value="human">
            <HumanEvaluationsSection run={data} scores={scores.data?.scores ?? []} names={names} />
          </TabsContent>
        </Tabs>
      </section>

      <ProvenanceSheet
        runId={id}
        criterionKey={criterionKey}
        round={round}
        criterionName={criterionKey ? names.get(criterionKey) : undefined}
        onOpenChange={(open) => !open && search.set({ criterion: undefined }, { resetPage: false })}
      />
    </RunDetailProvider>
  );
}
