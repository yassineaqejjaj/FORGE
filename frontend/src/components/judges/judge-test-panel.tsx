"use client";

import * as React from "react";
import Link from "next/link";
import { FlaskConical, Play } from "lucide-react";

import { ConfidenceMeter } from "@/components/domain/confidence-meter";
import { DimensionDot } from "@/components/domain/dimension-badge";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { CostDisplay, DurationDisplay, TokenCount } from "@/components/domain/metric-display";
import { ScoreBar } from "@/components/domain/score-bar";
import { SeverityBadge } from "@/components/domain/severity-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeBlock } from "@/components/ui/code-block";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { errorMessage } from "@/lib/api/client";
import { useTestJudge, type JudgeDetail, type JudgeTestVerdict } from "@/lib/api/judges";
import { formatNumber } from "@/lib/format";
import { RunPicker } from "./run-picker";

function promptText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  return JSON.stringify(value, null, 2);
}

/** Dry-run of the judge on an existing run (`POST /judges/{id}/test`, nothing persisted). */
export function JudgeTestPanel({ judge }: { judge: JudgeDetail }) {
  const [runIds, setRunIds] = React.useState<string[]>([]);
  const test = useTestJudge(judge.id);
  const result = test.data;
  const verdicts = (result?.verdicts ?? []) as unknown as JudgeTestVerdict[];
  const prompt = (result?.prompt ?? {}) as Record<string, unknown>;
  const promptExtras = Object.entries(prompt).filter(([k]) => k !== "system" && k !== "user");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FlaskConical className="size-4 text-muted-foreground" aria-hidden />
          Tester le juge sur un run
        </CardTitle>
        <CardDescription>
          Appel réel du juge sur la sortie et la trace d&apos;un run existant : verdicts et prompt rendu. Rien n&apos;est
          enregistré ; un juge LLM consomme des tokens.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <RunPicker mode="single" value={runIds} onChange={(ids) => setRunIds(ids)} />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            leftIcon={<Play aria-hidden />}
            disabled={!runIds[0]}
            loading={test.isPending}
            onClick={() => runIds[0] && test.mutate({ run_id: runIds[0] })}
          >
            Lancer le test
          </Button>
          {runIds[0] ? (
            <Button asChild variant="ghost" size="sm">
              <Link href={`/runs/${runIds[0]}`}>Voir le run</Link>
            </Button>
          ) : null}
        </div>
        {test.isError ? <Alert tone="red" title="Test impossible">{errorMessage(test.error)}</Alert> : null}

        {result ? (
          <div className="grid gap-4 border-t border-border pt-4">
            <div className="flex flex-wrap items-center gap-2 text-[13px]">
              <Badge tone={result.status === "ok" ? "green" : result.status === "partial" ? "amber" : "red"} dot>
                {result.status === "ok" ? "Succès" : result.status}
              </Badge>
              <Badge variant="outline">{result.model}</Badge>
              <DurationDisplay ms={result.latency_ms} />
              <TokenCount input={result.input_tokens} output={result.output_tokens} />
              <CostDisplay value={result.cost} />
              <Badge tone="neutral">Non enregistré</Badge>
            </div>
            {result.summary ? <p className="text-[13px] text-muted-foreground">{result.summary}</p> : null}
            {result.error ? <Alert tone="red">{result.error}</Alert> : null}
            {result.warnings.length ? (
              <Alert tone="amber" title="Avertissements">
                <ul>
                  {result.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </Alert>
            ) : null}
            {result.missing.length ? (
              <Alert tone="amber" title="Critères sans verdict">
                {result.missing.join(", ")} — aucun score n&apos;est inventé pour ces critères.
              </Alert>
            ) : null}

            <Tabs defaultValue="verdicts">
              <TabsList variant="pills">
                <TabsTrigger value="verdicts" count={verdicts.length}>
                  Verdicts
                </TabsTrigger>
                <TabsTrigger value="prompt">Prompt rendu</TabsTrigger>
              </TabsList>
              <TabsContent value="verdicts">
                <ul className="grid gap-2">
                  {verdicts.map((v) => (
                    <li key={v.criterion_key} className="grid gap-2 rounded-lg border border-border p-3">
                      <div className="flex flex-wrap items-center gap-3">
                        <span className="flex items-center gap-1.5 font-mono text-[12.5px] font-medium">
                          {v.dimension ? <DimensionDot dimension={v.dimension} /> : null}
                          {v.criterion_key}
                        </span>
                        <span className="text-xs tabular-nums text-muted-foreground">
                          {formatNumber(v.raw_score)} / {formatNumber(v.scale_max)}
                        </span>
                        <ScoreBar value={v.normalized_score} widthClassName="w-32" />
                        <ConfidenceMeter value={v.confidence} />
                      </div>
                      {v.explanation ? <p className="text-[13px] leading-relaxed">{v.explanation}</p> : null}
                      {v.evidence?.length ? (
                        <ul className="grid gap-1">
                          {v.evidence.map((ev, i) => (
                            <li key={i} className="rounded border-l-2 border-brand/50 bg-muted/40 px-2 py-1 text-[12.5px] text-muted-foreground">
                              {typeof ev.event === "number" ? <span className="mr-1 font-mono text-[11px]">[E{ev.event}]</span> : null}
                              {ev.excerpt ?? JSON.stringify(ev)}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {v.errors?.length ? (
                        <div className="flex flex-wrap gap-1.5">
                          {v.errors.map((er, i) => (
                            <span key={i} className="inline-flex items-center gap-1">
                              <ErrorTypeBadge code={String(er.type ?? er.error_type ?? "BAD_REASONING")} description={er.description} />
                              {er.severity ? <SeverityBadge severity={er.severity} /> : null}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </li>
                  ))}
                  {verdicts.length === 0 ? <p className="text-[13px] text-muted-foreground">Aucun verdict.</p> : null}
                </ul>
              </TabsContent>
              <TabsContent value="prompt" className="grid gap-3">
                <CodeBlock title="Système" code={promptText(prompt.system)} wrap maxHeightClassName="max-h-72" />
                <CodeBlock title="Utilisateur (grille rendue)" code={promptText(prompt.user)} wrap maxHeightClassName="max-h-[32rem]" />
                {promptExtras.length ? (
                  <CodeBlock title="Métadonnées" language="json" code={JSON.stringify(Object.fromEntries(promptExtras), null, 2)} wrap />
                ) : null}
              </TabsContent>
            </Tabs>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
