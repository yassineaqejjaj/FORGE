"use client";

import * as React from "react";
import { CircleAlert, CircleCheck, FlaskConical, Play, Wrench } from "lucide-react";

import { TraceEventTypeBadge } from "@/components/domain/enum-badge";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { CostDisplay, DurationDisplay, TokenCount } from "@/components/domain/metric-display";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeBlock } from "@/components/ui/code-block";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { JsonViewer } from "@/components/ui/json-viewer";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Textarea } from "@/components/ui/textarea";
import { useTestAgentVersion, type AgentTestOutput } from "@/lib/api/agents";
import { formatMs, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

import { JsonField, parseJsonText } from "./kit/json-field";
import { Markdown } from "./kit/markdown";
import { RoleButton } from "./kit/role-button";

interface TestEvent {
  seq?: number;
  type?: string;
  name?: string;
  status?: string;
  offset_ms?: number | null;
  duration_ms?: number | null;
}

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function asNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
function asString(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}

/** Ad-hoc call of an agent version (`POST /agent-versions/{id}/test`): output, events, usage, error. */
export function AgentTestPanel({ versionId }: { versionId: string }) {
  const test = useTestAgentVersion(versionId);
  const [mode, setMode] = React.useState<"prompt" | "json">("prompt");
  const [prompt, setPrompt] = React.useState("");
  const [inputJson, setInputJson] = React.useState('{\n  "prompt": ""\n}');
  const [contextJson, setContextJson] = React.useState("");

  const input = mode === "prompt" ? ({ ok: true, value: { prompt } } as const) : parseJsonText(inputJson);
  const context = parseJsonText(contextJson, null);
  const ready =
    input.ok &&
    context.ok &&
    (mode === "prompt" ? prompt.trim().length > 0 : Boolean(input.value && typeof input.value === "object"));

  const run = (e?: React.SyntheticEvent) => {
    e?.preventDefault();
    if (!ready || !input.ok || !context.ok) return;
    test.mutate({
      input: input.value as Record<string, unknown>,
      context: (context.value as Record<string, unknown> | null) ?? null,
    });
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
      <Card className="self-start">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FlaskConical className="size-4 text-muted-foreground" aria-hidden /> Tester l&apos;agent
          </CardTitle>
          <CardDescription>
            Appel ponctuel de cette version, hors évaluation : aucun run ni score n&apos;est créé. Les éventuels coûts du
            fournisseur s&apos;appliquent.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={run} className="grid gap-4">
            <SegmentedControl
              aria-label="Format de l'entrée"
              size="sm"
              value={mode}
              onValueChange={setMode}
              options={[
                { value: "prompt", label: "Prompt" },
                { value: "json", label: "Entrée JSON" },
              ]}
            />
            {mode === "prompt" ? (
              <Field id="test-prompt" label="Prompt" required>
                <Textarea
                  id="test-prompt"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={6}
                  placeholder="Rédige un PRD pour l'export CSV des factures…"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(e);
                  }}
                />
              </Field>
            ) : (
              <JsonField
                id="test-input"
                label="Entrée"
                value={inputJson}
                onChange={setInputJson}
                expect="object"
                rows={7}
                hint='{"prompt": "…"} ou {"messages": [{"role": "user", "content": "…"}]}'
              />
            )}
            <JsonField
              id="test-context"
              label="Contexte (optionnel)"
              value={contextJson}
              onChange={setContextJson}
              expect="object"
              rows={4}
              placeholder='{"documents": [{"id": "doc-1", "title": "…", "content": "…"}]}'
            />
            <RoleButton minRole="editor" type="submit" loading={test.isPending} disabled={!ready} leftIcon={<Play aria-hidden />}>
              Lancer l&apos;appel
            </RoleButton>
          </form>
        </CardContent>
      </Card>

      <div className="grid content-start gap-4">
        {test.isError ? (
          <Alert tone="red" title={test.error.isNotImplemented ? "Appel de test non disponible" : "L'appel a échoué"}>
            {test.error.detail}
          </Alert>
        ) : null}
        {test.data ? (
          <TestResult data={test.data} />
        ) : !test.isError ? (
          <EmptyState
            icon={<Play />}
            title={test.isPending ? "Appel en cours…" : "Aucun appel pour l'instant"}
            description="La sortie, les événements de la trace, les tokens, le coût et la latence s'afficheront ici."
          />
        ) : null}
      </div>
    </div>
  );
}

function TestResult({ data }: { data: AgentTestOutput }) {
  const result = asRecord(data.result);
  const usage = asRecord(result.token_usage);
  const events = (Array.isArray(result.events) ? result.events : []) as TestEvent[];
  const error = asString(result.error);
  const errorType = asString(result.error_type);
  const warnings = Array.isArray(result.warnings) ? (result.warnings as unknown[]).map(String) : [];
  const status = asString(result.status);
  const succeeded = !error && status !== "failed";
  const outputText = data.output_text ?? asString(result.output_text);

  return (
    <>
      <Card>
        <CardHeader className="flex-row flex-wrap items-center gap-2">
          <CardTitle className="mr-auto">Résultat</CardTitle>
          <Badge tone={succeeded ? "green" : "red"} icon={succeeded ? <CircleCheck aria-hidden /> : <CircleAlert aria-hidden />}>
            {succeeded ? "Succès" : "Échec"}
          </Badge>
        </CardHeader>
        <CardContent className="grid gap-4">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric label="Latence" value={<DurationDisplay ms={asNumber(result.latency_ms)} />} />
            <Metric
              label="Tokens"
              value={
                <TokenCount
                  total={asNumber(usage.total_tokens)}
                  input={asNumber(usage.input_tokens)}
                  output={asNumber(usage.output_tokens)}
                />
              }
            />
            <Metric label="Coût estimé" value={<CostDisplay value={asNumber(result.estimated_cost)} />} />
            <Metric
              label="Appels"
              value={
                <span className="tabular-nums">
                  {formatNumber(asNumber(result.model_calls) ?? 0, 0)} modèle · {formatNumber(asNumber(result.tool_calls) ?? 0, 0)} outil
                </span>
              }
            />
          </dl>

          {error ? (
            <Alert tone="red" title="Erreur de l'agent" action={errorType ? <ErrorTypeBadge code={errorType} /> : undefined}>
              {error}
              {result.retryable === true ? " (erreur transitoire : un nouvel essai peut réussir)" : null}
            </Alert>
          ) : null}
          {warnings.length ? (
            <Alert tone="amber" title="Avertissements">
              <ul className="list-disc pl-4">
                {warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </Alert>
          ) : null}

          <div className="grid gap-1.5">
            <p className="text-xs font-medium text-muted-foreground">Sortie</p>
            {outputText ? (
              <div className="max-h-[28rem] overflow-auto rounded-lg border border-border bg-muted/20 p-3">
                <Markdown>{outputText}</Markdown>
              </div>
            ) : (
              <p className="text-[13px] text-subtle-foreground">Sortie vide.</p>
            )}
            {outputText ? (
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Texte brut</summary>
                <CodeBlock code={outputText} wrap className="mt-2" />
              </details>
            ) : null}
          </div>
          {data.output_json !== null && data.output_json !== undefined ? (
            <div className="grid gap-1.5">
              <p className="text-xs font-medium text-muted-foreground">Sortie structurée</p>
              <JsonViewer data={data.output_json} defaultExpandDepth={2} />
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Événements</CardTitle>
          <CardDescription>Trace de l&apos;appel, dans l&apos;ordre d&apos;exécution</CardDescription>
        </CardHeader>
        <CardContent>
          {events.length ? (
            <EventsTimeline events={events} />
          ) : (
            <p className="text-[13px] text-subtle-foreground">Aucun événement rapporté.</p>
          )}
        </CardContent>
      </Card>
    </>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid gap-0.5 rounded-lg border border-border bg-muted/30 px-3 py-2">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">{label}</dt>
      <dd className="text-sm font-semibold text-foreground">{value}</dd>
    </div>
  );
}

function EventsTimeline({ events }: { events: TestEvent[] }) {
  const total = Math.max(1, ...events.map((e) => (asNumber(e.offset_ms) ?? 0) + (asNumber(e.duration_ms) ?? 0)));
  return (
    <ol className="grid gap-1">
      {events.map((e, i) => {
        const offset = asNumber(e.offset_ms) ?? 0;
        const duration = asNumber(e.duration_ms) ?? 0;
        const failed = e.status === "error";
        return (
          <li
            key={e.seq ?? i}
            className="grid grid-cols-[2rem_minmax(0,1fr)_minmax(5rem,9rem)] items-center gap-2 rounded-md px-1.5 py-1 text-xs hover:bg-muted/50 sm:grid-cols-[2rem_9rem_minmax(0,1fr)_minmax(6rem,12rem)]"
          >
            <span className="font-mono tabular-nums text-subtle-foreground">E{e.seq ?? i + 1}</span>
            <span className="hidden sm:block">
              <TraceEventTypeBadge value={e.type} />
            </span>
            <span className={cn("flex min-w-0 items-center gap-1.5 truncate", failed && "text-destructive")}>
              {e.type === "tool_call" ? <Wrench className="size-3.5 shrink-0" aria-hidden /> : null}
              <span className="truncate">{e.name ?? e.type}</span>
              {failed ? <CircleAlert className="size-3.5 shrink-0" aria-label="Erreur" /> : null}
            </span>
            <span className="flex items-center gap-2" title={`+${formatMs(offset)} · ${formatMs(duration)}`}>
              <span className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden>
                <span
                  className={cn("absolute inset-y-0 rounded-full", failed ? "bg-red-500" : "bg-brand")}
                  style={{ left: `${(offset / total) * 100}%`, width: `${Math.max(1.5, (duration / total) * 100)}%` }}
                />
              </span>
              <span className="w-14 shrink-0 text-right tabular-nums text-muted-foreground">{formatMs(duration)}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
