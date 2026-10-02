"use client";

import * as React from "react";
import { Activity, Bot, CircleCheck, CircleX, Database, Gavel, Ruler } from "lucide-react";

import { ConfidenceMeter } from "@/components/domain/confidence-meter";
import { DimensionDot } from "@/components/domain/dimension-badge";
import { JudgeProviderBadge, RuleTypeBadge } from "@/components/domain/enum-badge";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { CostDisplay, DurationDisplay, TokenCount } from "@/components/domain/metric-display";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { ScoreBar } from "@/components/domain/score-bar";
import { SeverityBadge } from "@/components/domain/severity-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { readEvidence, type Evaluation, type RunDetail } from "@/lib/api/runs";
import { formatNumber, formatScore } from "@/lib/format";
import { cn } from "@/lib/utils";
import { EvidenceList, EvidenceText } from "./evidence";
import { useRunDetail } from "./run-detail-context";

interface JudgeRef {
  judge_id?: string;
  key?: string;
  version?: number;
  name?: string;
  provider?: string;
  model?: string;
}

interface RuleRef {
  id?: string;
  type?: string;
  description?: string;
  params?: Record<string, unknown>;
  hidden?: boolean;
}

function judgesOf(run: RunDetail): JudgeRef[] {
  const judges = run.evaluation_config.judges;
  return Array.isArray(judges) ? (judges as JudgeRef[]) : [];
}

function rulesOf(run: RunDetail): RuleRef[] {
  const content = run.scenario.content as Record<string, unknown>;
  const scenarioRules = Array.isArray(content.rules) ? (content.rules as RuleRef[]) : [];
  return scenarioRules;
}

function CriterionLink({ criterionKey, label }: { criterionKey: string; label?: string | null }) {
  const ctx = useRunDetail();
  return (
    <button
      type="button"
      onClick={() => ctx?.openProvenance(criterionKey)}
      className="grid min-w-0 text-left hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      title="Voir la provenance du score"
    >
      {label ? <span className="truncate text-[13px] font-medium text-foreground">{label}</span> : null}
      <span className="truncate font-mono text-[11px] text-muted-foreground">{criterionKey}</span>
    </button>
  );
}

function Explanation({ evaluation }: { evaluation: Evaluation }) {
  if (evaluation.redacted) return <RedactedNotice variant="inline" title="Justification masquée (scénario privé)" />;
  return <EvidenceText text={evaluation.explanation} className="text-[13px] leading-relaxed text-foreground/90" />;
}

/* -------------------------------------------------------------------------- */
/* Judges                                                                     */
/* -------------------------------------------------------------------------- */

function JudgeCard({ judgeKey, items, judge, names }: { judgeKey: string; items: Evaluation[]; judge?: JudgeRef; names: Map<string, string> }) {
  const totalCost = items.reduce((s, e) => s + (e.cost ?? 0), 0);
  const latencies = items.map((e) => e.latency_ms).filter((v): v is number => typeof v === "number");
  const cachedCount = items.filter((e) => e.cached).length;
  const tokensIn = items.reduce((s, e) => s + (e.input_tokens ?? 0), 0);
  const tokensOut = items.reduce((s, e) => s + (e.output_tokens ?? 0), 0);
  const meanConfidence = items.reduce((s, e) => s + e.confidence, 0) / Math.max(1, items.length);
  const first = items[0];
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid gap-1">
            <CardTitle className="flex flex-wrap items-center gap-2">
              <Gavel className="size-4 text-violet-600 dark:text-violet-400" aria-hidden />
              {judge?.name ?? judgeKey}
              {judge?.provider ? <JudgeProviderBadge value={judge.provider} /> : null}
              {cachedCount ? (
                <SimpleTooltip content="Verdicts réutilisés depuis le cache des juges (même juge, scénario, sortie et trace) : coût nul.">
                  <span className="inline-flex">
                    <Badge tone="sky" icon={<Database aria-hidden />}>
                      {cachedCount === items.length ? "En cache" : `${cachedCount} en cache`}
                    </Badge>
                  </span>
                </SimpleTooltip>
              ) : null}
            </CardTitle>
            <CardDescription className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
              <span className="font-mono">{judgeKey}</span>
              {first?.judge_version ? <span>version {first.judge_version}</span> : null}
              {first?.model ? <span>modèle {first.model}</span> : null}
              {first?.prompt_hash ? <span className="font-mono" title={first.prompt_hash}>prompt {first.prompt_hash.replace("sha256:", "").slice(0, 10)}</span> : null}
            </CardDescription>
          </div>
          <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            <div>
              <dt className="text-muted-foreground">Confiance moy.</dt>
              <dd><ConfidenceMeter value={meanConfidence} /></dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Coût</dt>
              <dd className="font-medium"><CostDisplay value={totalCost} /></dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Latence</dt>
              <dd className="font-medium"><DurationDisplay ms={latencies.length ? Math.max(...latencies) : null} /></dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Tokens</dt>
              <dd className="font-medium"><TokenCount input={tokensIn} output={tokensOut} /></dd>
            </div>
          </dl>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y divide-border border-t border-border">
          {items.map((e) => {
            const evidence = readEvidence(e.evidence);
            const errors = Array.isArray(e.errors) ? (e.errors as Array<{ type?: string; severity?: string; description?: string }>) : [];
            return (
              <li key={e.id} className="grid gap-2 px-5 py-3 lg:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
                <div className="grid content-start gap-1.5">
                  <div className="flex items-center gap-1.5">
                    <DimensionDot dimension={e.dimension} />
                    <CriterionLink criterionKey={e.criterion_key} label={names.get(e.criterion_key)} />
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold tabular-nums">
                      {formatNumber(e.raw_score, 2)}
                      <span className="text-xs font-normal text-muted-foreground"> / {formatNumber(e.scale_max, 0)}</span>
                    </span>
                    <ScoreBar value={e.normalized_score} widthClassName="w-16" />
                  </div>
                  <ConfidenceMeter value={e.confidence} showLabel />
                </div>
                <div className="grid min-w-0 gap-2">
                  <Explanation evaluation={e} />
                  {evidence.length && !e.redacted ? <EvidenceList evidence={evidence} compact /> : null}
                  {errors.length ? (
                    <div className="flex flex-wrap gap-1.5">
                      {errors.map((err, i) => (
                        <span key={i} className="inline-flex items-center gap-1">
                          {err.type ? <ErrorTypeBadge code={err.type} /> : null}
                          {err.severity ? <SeverityBadge severity={err.severity} /> : null}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

/** Verdicts of each judge (per criterion: score, justification with [E12] links, evidence, confidence, cache, cost). */
export function JudgeEvaluationsSection({ run, evaluations, names }: { run: RunDetail; evaluations: Evaluation[]; names: Map<string, string> }) {
  const judged = evaluations.filter((e) => e.evaluator_kind === "llm_judge");
  const byJudge = new Map<string, Evaluation[]>();
  for (const e of judged) byJudge.set(e.evaluator_key, [...(byJudge.get(e.evaluator_key) ?? []), e]);
  const judges = judgesOf(run);
  if (!judged.length)
    return (
      <EmptyState
        size="sm"
        icon={<Bot />}
        title="Aucun verdict de juge"
        description="La configuration d'évaluation de ce round ne comporte pas de juge, ou aucun juge n'a produit de verdict."
      />
    );
  return (
    <div className="grid gap-4">
      {[...byJudge.entries()].map(([key, items]) => {
        const [base, version] = key.split("@v");
        const judge = judges.find((j) => j.key === base && (!version || String(j.version) === version)) ?? judges.find((j) => j.key === base);
        return <JudgeCard key={key} judgeKey={key} items={items} judge={judge} names={names} />;
      })}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Rules & metrics                                                            */
/* -------------------------------------------------------------------------- */

/** Deterministic rule results (pass / fail, explanation, evidence) and measured metrics. */
export function RuleResultsSection({ run, evaluations, names }: { run: RunDetail; evaluations: Evaluation[]; names: Map<string, string> }) {
  const rules = evaluations.filter((e) => e.evaluator_kind === "rule");
  const metrics = evaluations.filter((e) => e.evaluator_kind === "metric");
  const known = rulesOf(run);
  const passed = rules.filter((r) => r.passed).length;
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2">
            <Ruler className="size-4 text-blue-600 dark:text-blue-400" aria-hidden />
            Règles déterministes
            {rules.length ? (
              <Badge tone={passed === rules.length ? "green" : "amber"}>
                {passed} / {rules.length} respectées
              </Badge>
            ) : null}
          </CardTitle>
          <CardDescription>Contrôles gratuits et reproductibles du scénario et de la configuration.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {rules.length ? (
            <Table dense containerClassName="border-t border-border">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-24">Résultat</TableHead>
                  <TableHead>Règle</TableHead>
                  <TableHead>Critère</TableHead>
                  <TableHead className="text-right">Score</TableHead>
                  <TableHead className="min-w-[18rem]">Explication et preuves</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rules.map((r) => {
                  const ruleId = r.evaluator_key.split("#", 1)[0] ?? r.evaluator_key;
                  const def = known.find((k) => k.id === ruleId);
                  const evidence = readEvidence(r.evidence);
                  return (
                    <TableRow key={r.id} className={cn(r.passed === false && "bg-red-50/40 dark:bg-red-400/5")}>
                      <TableCell className="align-top">
                        {r.passed ? (
                          <Badge tone="green" icon={<CircleCheck aria-hidden />}>Réussie</Badge>
                        ) : (
                          <Badge tone="red" icon={<CircleX aria-hidden />}>Échec</Badge>
                        )}
                      </TableCell>
                      <TableCell className="align-top">
                        <div className="grid gap-1">
                          <span className="font-mono text-xs font-medium">{r.evaluator_key}</span>
                          {def?.type ? <RuleTypeBadge value={def.type} /> : null}
                          {def?.description ? <span className="text-xs text-muted-foreground">{def.description}</span> : null}
                        </div>
                      </TableCell>
                      <TableCell className="align-top">
                        <CriterionLink criterionKey={r.criterion_key} label={names.get(r.criterion_key)} />
                      </TableCell>
                      <TableCell className="text-right align-top font-medium tabular-nums">{formatScore(r.normalized_score)}</TableCell>
                      <TableCell className="align-top">
                        <div className="grid gap-1.5">
                          <Explanation evaluation={r} />
                          {evidence.length && !r.redacted ? <EvidenceList evidence={evidence} compact /> : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          ) : (
            <p className="border-t border-border px-5 py-4 text-[13px] text-muted-foreground">Aucune règle évaluée sur ce round.</p>
          )}
        </CardContent>
      </Card>
      {metrics.length ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <Activity className="size-4 text-sky-600 dark:text-sky-400" aria-hidden />
              Métriques mesurées
            </CardTitle>
            <CardDescription>Coût, latence et tokens normalisés selon les cibles de la configuration.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table dense containerClassName="border-t border-border">
              <TableHeader>
                <TableRow>
                  <TableHead>Critère</TableHead>
                  <TableHead className="text-right">Score</TableHead>
                  <TableHead>Calcul</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {metrics.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell>
                      <CriterionLink criterionKey={m.criterion_key} label={names.get(m.criterion_key)} />
                    </TableCell>
                    <TableCell className="text-right">
                      <ScoreBar value={m.normalized_score} widthClassName="w-16" />
                    </TableCell>
                    <TableCell className="text-[13px] text-foreground/90">{m.explanation}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
