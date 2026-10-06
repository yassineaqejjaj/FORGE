"use client";

import * as React from "react";
import Link from "next/link";
import { Check, CircleCheck, ShieldX, TriangleAlert } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { AdapterKindBadge } from "@/components/domain/enum-badge";
import { DurationDisplay } from "@/components/domain/metric-display";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { RelativeTime } from "@/components/domain/relative-time";
import { ScoreGauge } from "@/components/domain/score-gauge";
import { RunStatusBadge } from "@/components/domain/status-badge";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { SimpleSelect } from "@/components/ui/select";
import { isRunActive, type RunDetail } from "@/lib/api/runs";
import { BUILTIN_ERROR_TYPE_META, type BuiltinErrorType } from "@/lib/enums";
import { shortId, toDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { RunOrigin } from "../run-origin";
import { RunActions } from "./run-actions";

const STEPS = [
  { status: "pending", label: "En file" },
  { status: "running", label: "Exécution de l'agent" },
  { status: "evaluating", label: "Évaluation" },
  { status: "completed", label: "Terminé" },
] as const;

function LiveProgress({ status }: { status: string }) {
  const index = STEPS.findIndex((s) => s.status === status);
  return (
    <div className="grid gap-2 rounded-xl border border-blue-200 bg-blue-50/50 px-4 py-3 dark:border-blue-400/25 dark:bg-blue-400/5" role="status" aria-live="polite">
      <ol className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {STEPS.map((s, i) => (
          <li key={s.status} className={cn("flex items-center gap-1.5", i <= index ? "font-medium text-foreground" : "text-muted-foreground")}>
            <span
              className={cn(
                "flex size-4 items-center justify-center rounded-full text-[9px] font-semibold",
                i < index ? "bg-blue-600 text-white dark:bg-blue-400 dark:text-blue-950" : i === index ? "bg-blue-100 text-blue-800 ring-2 ring-blue-500 dark:bg-blue-400/20 dark:text-blue-200" : "bg-muted text-muted-foreground",
              )}
              aria-hidden
            >
              {i < index ? <Check className="size-2.5" /> : i + 1}
            </span>
            {s.label}
          </li>
        ))}
        <li className="ml-auto text-muted-foreground">Actualisation automatique…</li>
      </ol>
      <Progress value={null} tone="blue" size="xs" aria-label="Run en cours" />
    </div>
  );
}

export interface RunHeaderProps {
  run: RunDetail;
  rounds: number[];
  round: number | null;
  onRoundChange: (round: number | null) => void;
  onReevaluated: () => void;
}

/** Run Detail header: scenario + agent, status, composite gauge, pass / gate, round selector, actions, banners. */
export function RunHeader({ run, rounds, round, onRoundChange, onReevaluated }: RunHeaderProps) {
  const agent = run.agent as Record<string, unknown>;
  const agentLabel = String(agent.label ?? `${String(agent.name ?? "Agent")} v${String(agent.version ?? "")}`);
  const passThreshold = typeof run.evaluation_config.pass_threshold === "number" ? run.evaluation_config.pass_threshold : null;
  const latest = rounds.length ? Math.max(...rounds) : run.evaluation_round;
  const active = isRunActive(run.status);
  const started = toDate(run.started_at);
  const finished = toDate(run.finished_at);
  const errorMeta = run.error_type ? BUILTIN_ERROR_TYPE_META[run.error_type as BuiltinErrorType] : undefined;
  const viewingOld = round !== null && round !== latest;

  return (
    <div className="grid gap-3 pb-5">
      <ClassificationBanner level={run.scenario.classification} context="run" message={run.scenario.classification_warning ?? undefined} />

      <header className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 shadow-panel sm:p-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="grid min-w-0 gap-2">
          <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle-foreground">
            Run <span className="font-mono normal-case tracking-normal">{shortId(run.id)}</span>
          </p>
          <h1 className="text-xl font-semibold tracking-tight text-foreground sm:text-[22px]">{run.scenario.name}</h1>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
            {agent.agent_id ? (
              <Link href={`/agents/${String(agent.agent_id)}`} className="font-medium text-foreground hover:underline">
                {agentLabel}
              </Link>
            ) : (
              <span className="font-medium text-foreground">{agentLabel}</span>
            )}
            {modelLabel(agent.model) ? <span className="font-mono text-xs">{modelLabel(agent.model)}</span> : null}
            {agent.adapter_kind ? <AdapterKindBadge value={String(agent.adapter_kind)} withTooltip={false} /> : null}
          </p>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <RunStatusBadge status={run.status} size="md" detail={run.status_detail} />
            <RunOrigin
              origin={run.origin}
              benchmarkId={run.benchmark_id}
              benchmarkExecutionId={run.benchmark_execution_id}
              experimentId={run.experiment_id}
              experimentName={run.experiment_name}
              arm={run.arm}
            />
            <VisibilityBadge visibility={run.scenario.visibility} />
            <ClassificationBadge level={run.scenario.classification} />
            <Badge tone="neutral" variant="outline">Répétition {run.repetition}</Badge>
            <span className="ml-1">
              créé <RelativeTime date={run.created_at} />
            </span>
            {started && finished ? (
              <span>
                · durée <DurationDisplay ms={finished.getTime() - started.getTime()} />
              </span>
            ) : null}
          </div>
        </div>

        <div className="flex flex-col items-start gap-3 lg:items-end">
          <div className="flex items-center gap-4">
            <div className="grid gap-1.5 text-right">
              {run.gate_failed ? (
                <Badge tone="red" variant="solid" size="md" icon={<ShieldX aria-hidden />}>Garde-fou en échec</Badge>
              ) : run.passed === true ? (
                <Badge tone="green" size="md" icon={<CircleCheck aria-hidden />}>Réussi</Badge>
              ) : run.passed === false ? (
                <Badge tone="amber" size="md" dot>Sous le seuil</Badge>
              ) : (
                <Badge tone="neutral" size="md" variant="outline">Non évalué</Badge>
              )}
              {passThreshold !== null ? <span className="text-xs text-muted-foreground">seuil {passThreshold}</span> : null}
              {rounds.length > 1 ? (
                <SimpleSelect
                  size="sm"
                  aria-label="Round d'évaluation"
                  className="w-44"
                  value={String(round ?? latest)}
                  onValueChange={(v) => onRoundChange(Number(v) === latest ? null : Number(v))}
                  options={[...rounds]
                    .sort((a, b) => b - a)
                    .map((r) => ({ value: String(r), label: `Round ${r}${r === latest ? " (dernier)" : ""}` }))}
                />
              ) : null}
            </div>
            <ScoreGauge value={run.composite_score} size="md" label="Composite" passThreshold={passThreshold} passed={run.passed} gateFailed={run.gate_failed} />
          </div>
          <RunActions run={run} onReevaluated={onReevaluated} />
        </div>
      </header>

      {active ? <LiveProgress status={run.status} /> : null}

      {viewingOld ? (
        <Alert tone="sky" title={`Vous consultez le round ${round}`}>
          Le score affiché dans l&apos;en-tête est celui du dernier round ({latest}). Les sections ci-dessous montrent le round {round}.
        </Alert>
      ) : null}

      {run.error ? (
        <Alert tone="red" icon={<TriangleAlert aria-hidden />} title={errorMeta ? `${errorMeta.label} (${run.error_type})` : "Erreur d'exécution"}>
          {run.error}
        </Alert>
      ) : null}
      {run.status_detail && !run.error ? <Alert tone="amber" title="Avertissement">{run.status_detail}</Alert> : null}
      {run.redacted ? <RedactedNotice /> : null}
    </div>
  );
}

/** The run detail exposes the frozen ``ModelSpec`` (object) — older payloads a plain model name. */
function modelLabel(model: unknown): string | null {
  if (!model) return null;
  if (typeof model === "string") return model;
  if (typeof model === "object" && "model" in model) {
    const spec = model as { model?: unknown; model_version?: unknown };
    const name = typeof spec.model === "string" ? spec.model : null;
    const version = typeof spec.model_version === "string" ? spec.model_version : null;
    return name ? (version ? `${name} (${version})` : name) : null;
  }
  return null;
}
