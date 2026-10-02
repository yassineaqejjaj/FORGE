"use client";

import * as React from "react";
import { Bot, ChevronRight, Database, FileCode2, Gavel, Ruler, Sigma } from "lucide-react";

import { ConfidenceMeter } from "@/components/domain/confidence-meter";
import { DimensionBadge } from "@/components/domain/dimension-badge";
import { AggregationMethodBadge, EvaluatorKindBadge, JudgeProviderBadge, RuleTypeBadge, ScoreSourceBadge } from "@/components/domain/enum-badge";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { CostDisplay, DurationDisplay, TokenCount } from "@/components/domain/metric-display";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { ScoreBar } from "@/components/domain/score-bar";
import { SeverityBadge } from "@/components/domain/severity-badge";
import { Badge } from "@/components/ui/badge";
import { CodeBlock } from "@/components/ui/code-block";
import { ErrorState } from "@/components/ui/error-state";
import { JsonViewer } from "@/components/ui/json-viewer";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  readEvidence,
  readVerdicts,
  useScoreProvenance,
  type Provenance,
  type ProvenanceAggregation,
  type ProvenanceEvaluator,
} from "@/lib/api/runs";
import { formatNumber, formatPercent, formatScore, formatScore100 } from "@/lib/format";
import { cn } from "@/lib/utils";
import { EventRef, EvidenceList, EvidenceText } from "./evidence";

function Block({ icon, title, children, className }: { icon?: React.ReactNode; title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("grid gap-2", className)}>
      <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-subtle-foreground [&_svg]:size-3.5">
        {icon}
        {title}
      </h3>
      {children}
    </section>
  );
}

function KV({ label, children, mono }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className={cn("min-w-0 break-words text-[13px]", mono && "font-mono text-xs")}>{children ?? "—"}</dd>
    </div>
  );
}

function Collapsible({ title, children, defaultOpen = false }: { title: React.ReactNode; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <div className="rounded-lg border border-border">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] font-medium hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronRight className={cn("size-4 text-subtle-foreground transition-transform", open && "rotate-90")} aria-hidden />
        {title}
      </button>
      {open ? <div className="grid gap-2 border-t border-border p-3">{children}</div> : null}
    </div>
  );
}

function AggregationBlock({ agg }: { agg: ProvenanceAggregation }) {
  const verdicts = readVerdicts(agg.individual_verdicts);
  return (
    <div className="grid gap-3 rounded-lg border border-border bg-muted/30 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <ScoreSourceBadge value={agg.source} />
        <Badge tone="neutral" variant="outline" mono>
          {agg.method}
        </Badge>
        {agg.configured_method && agg.configured_method !== agg.method ? (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            configuré : <AggregationMethodBadge value={agg.configured_method} />
          </span>
        ) : null}
        <span className="ml-auto flex items-center gap-3">
          <ScoreBar value={agg.value} widthClassName="w-20" />
          <ConfidenceMeter value={agg.confidence} />
        </span>
      </div>
      <p className="text-[13px] leading-relaxed">
        <EvidenceText text={agg.explanation} />
      </p>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {typeof agg.spread === "number" ? (
          <span>
            Désaccord (max − min) : <span className={cn("font-medium tabular-nums", agg.spread >= 0.3 ? "text-red-700 dark:text-red-300" : "text-foreground")}>{formatScore(agg.spread)}</span>
          </span>
        ) : null}
        {agg.expression ? (
          <span>
            Expression : <code className="font-mono text-foreground">{agg.expression}</code>
          </span>
        ) : null}
        {agg.weights && Object.keys(agg.weights).length ? (
          <span>
            Poids : {Object.entries(agg.weights).map(([k, v]) => `${k} ${formatNumber(v)}`).join(" · ")}
          </span>
        ) : null}
      </div>
      {verdicts.length ? (
        <Table dense containerClassName="rounded-md border border-border bg-card">
          <TableHeader>
            <TableRow>
              <TableHead>Évaluateur</TableHead>
              <TableHead className="text-right">Note brute</TableHead>
              <TableHead className="text-right">Normalisée</TableHead>
              <TableHead>Confiance</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {verdicts.map((v) => (
              <TableRow key={v.evaluation_id}>
                <TableCell>
                  <span className="flex items-center gap-1.5">
                    <EvaluatorKindBadge value={v.evaluator_kind} withTooltip={false} />
                    <span className="font-mono text-xs">{v.evaluator_key}</span>
                  </span>
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(v.raw_score, 2)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatScore(v.normalized_score)}</TableCell>
                <TableCell>
                  <ConfidenceMeter value={v.confidence} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}
    </div>
  );
}

function EvaluatorBlock({ ev, promptsVisible }: { ev: ProvenanceEvaluator; promptsVisible: boolean }) {
  const e = ev.evaluation;
  const evidence = readEvidence(e.evidence);
  const icon = e.evaluator_kind === "llm_judge" ? <Gavel aria-hidden /> : e.evaluator_kind === "rule" ? <Ruler aria-hidden /> : <Sigma aria-hidden />;
  return (
    <li className="grid gap-3 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2 [&>svg]:size-4 [&>svg]:text-muted-foreground">
        {icon}
        <EvaluatorKindBadge value={e.evaluator_kind} />
        <span className="font-mono text-xs font-medium">{e.evaluator_key}</span>
        {e.cached ? (
          <Badge tone="sky" icon={<Database aria-hidden />}>
            En cache
          </Badge>
        ) : null}
        <span className="ml-auto flex items-center gap-3 text-xs">
          <span className="font-semibold tabular-nums">
            {formatNumber(e.raw_score, 2)} <span className="font-normal text-muted-foreground">/ {formatNumber(e.scale_max)}</span>
          </span>
          <ConfidenceMeter value={e.confidence} />
        </span>
      </div>

      {ev.judge ? (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <KV label="Juge">
            {ev.judge.name ?? ev.judge.key} {ev.judge.version ? <span className="text-muted-foreground">v{ev.judge.version}</span> : null}
          </KV>
          <KV label="Fournisseur">{ev.judge.provider ? <JudgeProviderBadge value={ev.judge.provider} /> : "—"}</KV>
          <KV label="Modèle" mono>
            {ev.judge.model ?? e.model ?? "—"}
          </KV>
          <KV label="Poids du juge">{typeof ev.judge.weight === "number" ? formatNumber(ev.judge.weight) : "—"}</KV>
          <KV label="Empreinte du juge" mono>
            <span title={ev.judge.content_hash ?? undefined}>{ev.judge.content_hash?.replace("sha256:", "").slice(0, 16) ?? "—"}</span>
          </KV>
          <KV label="Empreinte du prompt" mono>
            <span title={e.prompt_hash ?? undefined}>{e.prompt_hash?.replace("sha256:", "").slice(0, 16) ?? "—"}</span>
          </KV>
        </dl>
      ) : null}

      {ev.rule ? (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <KV label="Règle" mono>
            {ev.rule.id}
          </KV>
          <KV label="Type">{ev.rule.type ? <RuleTypeBadge value={ev.rule.type} /> : "—"}</KV>
          <KV label="Origine">{ev.rule.source === "configuration" ? "Configuration d'évaluation" : "Scénario"}</KV>
          <KV label="Poids">{typeof ev.rule.weight === "number" ? formatNumber(ev.rule.weight) : "—"}</KV>
          <KV label="Gravité en cas d'échec">{ev.rule.severity ? <SeverityBadge severity={ev.rule.severity} /> : "—"}</KV>
          <KV label="Résultat">
            {e.passed === true ? <Badge tone="green">Réussie</Badge> : e.passed === false ? <Badge tone="red">Échec</Badge> : "—"}
          </KV>
          {ev.rule.description ? <KV label="Description">{ev.rule.description}</KV> : null}
        </dl>
      ) : null}
      {ev.rule && (ev.rule.redacted || ev.rule.hidden) ? (
        <RedactedNotice variant="inline" title={ev.rule.hidden ? "Règle cachée : paramètres masqués" : "Paramètres masqués (scénario privé)"} />
      ) : ev.rule && Object.keys(ev.rule.params ?? {}).length ? (
        <Collapsible title="Paramètres de la règle">
          <JsonViewer data={ev.rule.params} defaultExpandDepth={2} maxHeightClassName="max-h-56" />
        </Collapsible>
      ) : null}

      {ev.metric ? (
        <dl className="grid grid-cols-3 gap-3">
          {Object.entries(ev.metric).map(([k, v]) => (
            <KV key={k} label={k === "value" ? "Valeur mesurée" : k === "target" ? "Cible (score 1)" : k === "max" ? "Maximum (score 0)" : k}>
              {typeof v === "number" ? formatNumber(v, 4) : String(v)}
            </KV>
          ))}
        </dl>
      ) : null}

      <div className="grid gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-subtle-foreground">Justification</span>
        {e.redacted ? (
          <RedactedNotice variant="inline" title="Justification masquée (scénario privé)" />
        ) : (
          <p className="text-[13px] leading-relaxed">
            <EvidenceText text={e.explanation} />
          </p>
        )}
      </div>
      {evidence.length && !e.redacted ? <EvidenceList evidence={evidence} compact /> : null}

      {ev.trace_events?.length ? (
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          Événements de trace référencés :
          {(ev.trace_events ?? []).map((t) => (
            <span key={t.seq} className="inline-flex items-center gap-1 rounded-md border border-border px-1.5 py-0.5">
              <EventRef seq={t.seq} />
              <span className="max-w-40 truncate text-foreground">{t.name ?? t.type}</span>
            </span>
          ))}
        </div>
      ) : null}

      {e.evaluator_kind === "llm_judge" ? (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>
            Coût <CostDisplay value={e.cost} className="text-foreground" />
          </span>
          <span>
            Latence <DurationDisplay ms={e.latency_ms} className="text-foreground" />
          </span>
          <span>
            Tokens <TokenCount input={e.input_tokens} output={e.output_tokens} className="text-foreground" />
          </span>
        </div>
      ) : null}

      {ev.prompt ? (
        promptsVisible && ev.prompt.available ? (
          <Collapsible title={<span className="flex items-center gap-1.5"><FileCode2 className="size-3.5" aria-hidden />Prompt rendu (mainteneurs)</span>}>
            {ev.prompt.system ? <CodeBlock title="Système" code={ev.prompt.system} wrap maxHeightClassName="max-h-64" /> : null}
            {ev.prompt.user ? <CodeBlock title="Utilisateur (rubrique rendue)" code={ev.prompt.user} wrap maxHeightClassName="max-h-96" /> : null}
          </Collapsible>
        ) : (
          <p className="text-xs text-muted-foreground">
            Prompt rendu réservé aux mainteneurs{ev.prompt.prompt_hash ? ` · empreinte ${ev.prompt.prompt_hash.replace("sha256:", "").slice(0, 16)}` : ""}.
          </p>
        )
      ) : null}
    </li>
  );
}

function ProvenanceBody({ data }: { data: Provenance }) {
  const c = data.criterion;
  const comp = data.composite;
  return (
    <div className="grid gap-6">
      {data.redacted ? <RedactedNotice description="Scénario privé : justifications, preuves, paramètres de règles et prompts sont masqués ; les scores et la méthode restent visibles." /> : null}

      <Block title="Critère">
        <div className="grid gap-2 rounded-lg border border-border p-3">
          <div className="flex flex-wrap items-center gap-2">
            <DimensionBadge dimension={c.dimension} />
            <Badge tone="neutral" variant="outline">
              échelle {formatNumber(c.scale_min)}–{formatNumber(c.scale_max)}
            </Badge>
            <Badge tone="neutral" variant="outline">
              poids {formatNumber(c.weight)}
            </Badge>
          </div>
          {c.question ? <p className="text-[13px] leading-relaxed">{c.question}</p> : null}
          {c.rubric ? <p className="text-xs leading-relaxed text-muted-foreground">{c.rubric}</p> : null}
        </div>
      </Block>

      <Block icon={<Sigma aria-hidden />} title="Score final">
        <ul className="grid gap-2">
          {data.scores.map((s) => (
            <li key={s.id} className={cn("grid gap-1.5 rounded-lg border p-3", s.used_in_composite ? "border-brand/40 bg-brand-soft/40" : "border-border")}>
              <div className="flex flex-wrap items-center gap-2">
                <ScoreSourceBadge value={s.source} />
                <span className="text-lg font-semibold tabular-nums">{formatScore(s.value)}</span>
                <ScoreBar value={s.value} showValue={false} widthClassName="w-24" />
                <ConfidenceMeter value={s.confidence} />
                <Badge tone={s.used_in_composite ? "orange" : "neutral"} variant="outline" className="ml-auto">
                  {s.used_in_composite ? "Retenu dans le composite" : "Non retenu"}
                </Badge>
              </div>
              <p className="text-[13px] leading-relaxed">
                <EvidenceText text={s.explanation} />
              </p>
            </li>
          ))}
        </ul>
      </Block>

      {comp ? (
        <Block title="Contribution au composite">
          <dl className="grid grid-cols-2 gap-3 rounded-lg border border-border p-3 sm:grid-cols-4">
            <KV label="Dimension">{formatScore(comp.dimension_value)}</KV>
            <KV label="Poids de la dimension">{typeof comp.dimension_weight === "number" ? formatPercent(comp.dimension_weight) : "—"}</KV>
            <KV label="Poids effectif">{typeof comp.effective_weight === "number" ? formatPercent(comp.effective_weight, 1) : "—"}</KV>
            <KV label="Poids du critère">{formatNumber(comp.criterion_weight)}</KV>
            <KV label="Composite du round">{formatScore100(comp.composite)}</KV>
          </dl>
          {comp.formula ? <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 font-mono text-[11.5px] leading-relaxed">{comp.formula}</p> : null}
        </Block>
      ) : null}

      {data.aggregations.length ? (
        <Block icon={<Bot aria-hidden />} title="Agrégation">
          <div className="grid gap-2">
            {data.aggregations.map((a, i) => (
              <AggregationBlock key={`${a.source}-${i}`} agg={a} />
            ))}
          </div>
        </Block>
      ) : null}

      <Block icon={<Gavel aria-hidden />} title={`Évaluateurs (${data.evaluators.length})`}>
        <ul className="grid gap-3">
          {data.evaluators.map((ev) => (
            <EvaluatorBlock key={ev.evaluation.id} ev={ev} promptsVisible={data.prompts_visible} />
          ))}
        </ul>
      </Block>

      {data.errors?.length ? (
        <Block title="Erreurs liées">
          <ul className="grid gap-2">
            {(data.errors ?? []).map((err) => (
              <li key={err.id} className="grid gap-1 rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <ErrorTypeBadge code={err.error_type} label={err.label} />
                  <SeverityBadge severity={err.severity} />
                  {typeof err.trace_event_seq === "number" ? <EventRef seq={err.trace_event_seq} /> : null}
                </div>
                {err.redacted ? null : (
                  <p className="text-[13px]">
                    <EvidenceText text={err.description} />
                  </p>
                )}
              </li>
            ))}
          </ul>
        </Block>
      ) : null}

      <p className="text-[11px] text-muted-foreground">
        Configuration {String(data.evaluation_config.key ?? "")} v{String(data.evaluation_config.version ?? "")} · round {data.round}
      </p>
    </div>
  );
}

export interface ProvenanceSheetProps {
  runId: string;
  criterionKey: string | null;
  round: number | null;
  criterionName?: string;
  onOpenChange: (open: boolean) => void;
}

/** "Why this score?" — evaluators, judges (key, version, prompt hash, model), rules, evidence, aggregation. */
export function ProvenanceSheet({ runId, criterionKey, round, criterionName, onOpenChange }: ProvenanceSheetProps) {
  const prov = useScoreProvenance(runId, criterionKey, round);
  return (
    <Sheet open={criterionKey !== null} onOpenChange={onOpenChange}>
      <SheetContent size="xl">
        <SheetHeader>
          <SheetTitle>Provenance du score · {prov.data?.criterion.name ?? criterionName ?? criterionKey}</SheetTitle>
          <SheetDescription className="font-mono text-xs">{criterionKey}</SheetDescription>
        </SheetHeader>
        <SheetBody>
          {prov.isPending ? (
            <div className="grid gap-3">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-48 w-full" />
            </div>
          ) : prov.isError ? (
            <ErrorState error={prov.error} onRetry={() => void prov.refetch()} />
          ) : (
            <ProvenanceBody data={prov.data} />
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}
