"use client";

import * as React from "react";
import Link from "next/link";
import { BookOpen, ChevronRight, ExternalLink, ListChecks, MessageSquareQuote, Target } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { DifficultyBadge } from "@/components/domain/enum-badge";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { JsonViewer } from "@/components/ui/json-viewer";
import type { RunDetail } from "@/lib/api/runs";
import { scenarioCategoryLabel } from "@/lib/enums";
import { cn } from "@/lib/utils";
import { Markdown } from "./markdown";

type Dict = Record<string, unknown>;

const isDict = (v: unknown): v is Dict => typeof v === "object" && v !== null && !Array.isArray(v);
const isEmpty = (v: unknown) =>
  v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0) || (isDict(v) && Object.keys(v).length === 0);

const PROMPT_KEYS = ["prompt", "message", "question", "query", "request", "text", "brief"] as const;

interface ContextDocument {
  id?: string;
  title?: string;
  content?: unknown;
  source?: string;
  [key: string]: unknown;
}

function Section({ icon, title, children, aside }: { icon: React.ReactNode; title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="grid gap-2">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-subtle-foreground [&_svg]:size-3.5">
        {icon}
        {title}
        {aside ? <span className="ml-auto font-normal normal-case tracking-normal">{aside}</span> : null}
      </h3>
      {children}
    </section>
  );
}

function TextOrJson({ value }: { value: unknown }) {
  if (typeof value === "string") return <Markdown className="text-[13px]">{value}</Markdown>;
  return <JsonViewer data={value} defaultExpandDepth={2} maxHeightClassName="max-h-72" />;
}

function InputView({ input }: { input: unknown }) {
  if (isEmpty(input)) return <p className="text-[13px] text-muted-foreground">Aucune entrée.</p>;
  if (typeof input === "string") return <blockquote className="rounded-lg border-l-2 border-brand bg-muted/40 px-3 py-2 text-[13px] leading-relaxed">{input}</blockquote>;
  if (!isDict(input)) return <JsonViewer data={input} defaultExpandDepth={2} />;
  const promptKey = PROMPT_KEYS.find((k) => typeof input[k] === "string");
  const messages = Array.isArray(input.messages) ? (input.messages as Array<Dict>) : null;
  const rest = Object.fromEntries(Object.entries(input).filter(([k]) => k !== promptKey && k !== "messages"));
  return (
    <div className="grid gap-2">
      {promptKey ? (
        <blockquote className="whitespace-pre-line rounded-lg border-l-2 border-brand bg-muted/40 px-3 py-2 text-[13px] leading-relaxed text-foreground">
          {String(input[promptKey])}
        </blockquote>
      ) : null}
      {messages ? (
        <ol className="grid gap-1.5">
          {messages.map((m, i) => (
            <li key={i} className="rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px]">
              <span className="mr-1.5 text-[11px] font-semibold uppercase tracking-wide text-subtle-foreground">{String(m.role ?? "message")}</span>
              <span className="whitespace-pre-line">{typeof m.content === "string" ? m.content : JSON.stringify(m.content)}</span>
            </li>
          ))}
        </ol>
      ) : null}
      {Object.keys(rest).length ? (
        <dl className="grid gap-1 text-xs">
          {Object.entries(rest).map(([k, v]) => (
            <div key={k} className="flex min-w-0 gap-2">
              <dt className="shrink-0 font-mono text-muted-foreground">{k}</dt>
              <dd className="min-w-0 break-words text-foreground">{typeof v === "string" || typeof v === "number" || typeof v === "boolean" ? String(v) : JSON.stringify(v)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

function DocumentItem({ doc, index }: { doc: ContextDocument; index: number }) {
  const [open, setOpen] = React.useState(false);
  const content = doc.content;
  return (
    <li className="rounded-lg border border-border bg-background">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px] hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronRight className={cn("size-4 shrink-0 text-subtle-foreground transition-transform", open && "rotate-90")} aria-hidden />
        {doc.id ? <Badge mono tone="neutral" variant="outline">{doc.id}</Badge> : null}
        <span className="truncate font-medium">{doc.title ?? `Document ${index + 1}`}</span>
      </button>
      {open ? (
        <div className="border-t border-border px-3 py-2">
          {typeof content === "string" ? (
            <p className="whitespace-pre-line text-[12.5px] leading-relaxed text-foreground/90">{content}</p>
          ) : (
            <JsonViewer data={doc} defaultExpandDepth={1} maxHeightClassName="max-h-64" />
          )}
        </div>
      ) : null}
    </li>
  );
}

function ContextView({ context }: { context: unknown }) {
  if (isEmpty(context)) return <p className="text-[13px] text-muted-foreground">Aucun contexte fourni.</p>;
  if (!isDict(context)) return <TextOrJson value={context} />;
  const docs = Array.isArray(context.documents) ? (context.documents as ContextDocument[]) : [];
  const rest = Object.fromEntries(Object.entries(context).filter(([k]) => k !== "documents"));
  return (
    <div className="grid gap-2">
      {docs.length ? (
        <ul className="grid gap-1.5">
          {docs.map((d, i) => (
            <DocumentItem key={d.id ?? i} doc={d} index={i} />
          ))}
        </ul>
      ) : null}
      {Object.keys(rest).length ? <JsonViewer data={rest} defaultExpandDepth={1} maxHeightClassName="max-h-64" /> : null}
    </div>
  );
}

export interface ScenarioPanelProps {
  run: RunDetail;
  /** Hide the identity card (review workspace shows its own header). */
  compact?: boolean;
}

/** Left column: what the agent was asked (scenario identity, input, context, expected result, constraints). */
export function ScenarioPanel({ run, compact = false }: ScenarioPanelProps) {
  const scenario = run.scenario;
  const content = (scenario.content ?? {}) as Dict;
  const redacted = run.redacted || content.redacted === true;
  const constraints = Array.isArray(content.constraints) ? (content.constraints as unknown[]) : [];
  const context = content.context;
  const docCount = isDict(context) && Array.isArray(context.documents) ? context.documents.length : 0;

  return (
    <div className="grid gap-4">
      {!compact ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-start justify-between gap-2">
              <span className="min-w-0">{scenario.name}</span>
              <Link
                href={`/scenarios/${scenario.id}`}
                className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="Ouvrir le scénario"
                title="Ouvrir le scénario"
              >
                <ExternalLink className="size-3.5" aria-hidden />
              </Link>
            </CardTitle>
            <p className="break-all font-mono text-[11.5px] text-muted-foreground">
              {scenario.slug}
              {scenario.version ? ` · v${scenario.version}` : ""}
              {scenario.variant_label ? ` · variante ${scenario.variant_label}` : ""}
            </p>
          </CardHeader>
          <CardContent className="grid gap-3">
            <div className="flex flex-wrap gap-1.5">
              <Badge tone="neutral" variant="outline">{scenarioCategoryLabel(scenario.category)}</Badge>
              {scenario.difficulty ? <DifficultyBadge value={scenario.difficulty} /> : null}
              <VisibilityBadge visibility={scenario.visibility} />
              <ClassificationBadge level={scenario.classification} />
            </div>
            {scenario.tags?.length ? (
              <div className="flex flex-wrap gap-1">
                {(scenario.tags ?? []).map((t) => (
                  <Badge key={t} tone="neutral">#{t}</Badge>
                ))}
              </div>
            ) : null}
            {!redacted && typeof content.description === "string" && content.description ? (
              <p className="text-[13px] leading-relaxed text-muted-foreground">{content.description}</p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardContent className="grid gap-5 pt-5">
          {redacted ? (
            <RedactedNotice description="Scénario privé : les résultats restent visibles, mais l'entrée, le contexte, le résultat attendu et les contraintes sont réservés aux mainteneurs." />
          ) : (
            <>
              <Section icon={<MessageSquareQuote aria-hidden />} title="Entrée">
                <InputView input={content.input} />
              </Section>
              <Section icon={<BookOpen aria-hidden />} title="Contexte" aside={docCount ? `${docCount} document${docCount > 1 ? "s" : ""}` : undefined}>
                <ContextView context={context} />
              </Section>
              <Section icon={<Target aria-hidden />} title="Résultat attendu">
                {isEmpty(content.expected_output) && isEmpty(content.expected_behavior) ? (
                  <p className="text-[13px] text-muted-foreground">Non précisé.</p>
                ) : (
                  <div className="grid gap-2">
                    {!isEmpty(content.expected_output) ? <TextOrJson value={content.expected_output} /> : null}
                    {!isEmpty(content.expected_behavior) ? (
                      <div className="grid gap-1">
                        <span className="text-[11px] font-medium text-muted-foreground">Comportement attendu</span>
                        <TextOrJson value={content.expected_behavior} />
                      </div>
                    ) : null}
                  </div>
                )}
              </Section>
              <Section icon={<ListChecks aria-hidden />} title="Contraintes">
                {constraints.length ? (
                  <ul className="grid gap-1 text-[13px]">
                    {constraints.map((c, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand" aria-hidden />
                        <span>{typeof c === "string" ? c : JSON.stringify(c)}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[13px] text-muted-foreground">Aucune contrainte explicite.</p>
                )}
              </Section>
              {typeof content.canary === "string" ? (
                <p className="text-[11px] text-muted-foreground">
                  Canari (mainteneurs) : <span className="font-mono">{content.canary}</span>
                </p>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
