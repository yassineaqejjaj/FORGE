"use client";

import * as React from "react";
import { BookOpen, EyeOff, FileText, ListChecks, MessageSquare, Ruler, Scale, ShieldCheck, Target, Wrench } from "lucide-react";

import { DetailList } from "@/components/agents/kit/detail-list";
import { Markdown } from "@/components/agents/kit/markdown";
import { DimensionBadge } from "@/components/domain/dimension-badge";
import { RuleTypeBadge } from "@/components/domain/enum-badge";
import { ErrorTypeBadge } from "@/components/domain/error-type-badge";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { SeverityBadge } from "@/components/domain/severity-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CopyButton } from "@/components/ui/code-block";
import { JsonViewer } from "@/components/ui/json-viewer";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useMeta, type Meta, type ScenarioVersion } from "@/lib/api/scenarios";
import { criterionDimension } from "@/lib/enums";
import { formatNumber, plural, truncate } from "@/lib/format";
import { cn } from "@/lib/utils";

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

/** Short human summary of rule params ("sections : Objectifs, Critères · mode : all"). */
export function paramsSummary(params: unknown): string {
  const rec = asRecord(params);
  if (!rec || Object.keys(rec).length === 0) return "—";
  return Object.entries(rec)
    .map(([k, v]) => {
      let text: string;
      if (Array.isArray(v)) text = v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ");
      else if (v && typeof v === "object") text = JSON.stringify(v);
      else text = String(v);
      return `${k} : ${truncate(text, 80)}`;
    })
    .join(" · ");
}

function Section({ icon, title, description, children, aside }: { icon: React.ReactNode; title: string; description?: React.ReactNode; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="flex-row items-start gap-3">
        <div className="grid min-w-0 flex-1 gap-1">
          <CardTitle className="flex items-center gap-2 [&_svg]:size-4 [&_svg]:text-muted-foreground">
            {icon}
            {title}
          </CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </div>
        {aside}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function Hidden() {
  return <RedactedNotice variant="inline" />;
}

function Muted({ children }: { children: React.ReactNode }) {
  return <p className="text-[13px] text-subtle-foreground">{children}</p>;
}

function criterionName(meta: Meta | undefined, key: string): string | undefined {
  return meta?.criteria.find((c) => c.key === key)?.name;
}

/** Read-only content of a scenario version, with redaction placeholders (decided by the API). */
export function ScenarioContent({ version, showCanary = true }: { version: ScenarioVersion; showCanary?: boolean }) {
  const meta = useMeta().data;
  const redacted = version.redacted;
  const input = asRecord(version.input);
  const context = asRecord(version.context);

  return (
    <div className="grid gap-4">
      {redacted ? <RedactedNotice /> : null}

      {version.description || (redacted && version.description == null) ? (
        <Section icon={<FileText />} title="Description">
          {version.description ? <Markdown>{version.description}</Markdown> : <Hidden />}
        </Section>
      ) : null}

      <Section icon={<MessageSquare />} title="Entrée de l'agent" description="Ce que reçoit l'agent (avec le contexte et les contraintes).">
        {input ? <InputView input={input} /> : redacted ? <Hidden /> : <Muted>Aucune entrée.</Muted>}
      </Section>

      <Section
        icon={<BookOpen />}
        title="Contexte"
        description={context && Array.isArray(context.documents) ? plural(context.documents.length, "document") : undefined}
      >
        {context ? <ContextView context={context} /> : redacted ? <Hidden /> : <Muted>Aucun contexte.</Muted>}
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section icon={<ListChecks />} title="Contraintes">
          {version.constraints ? (
            version.constraints.length ? (
              <ul className="grid gap-1.5">
                {version.constraints.map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-[13px]">
                    <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand" aria-hidden />
                    {c}
                  </li>
                ))}
              </ul>
            ) : (
              <Muted>Aucune contrainte.</Muted>
            )
          ) : redacted ? (
            <Hidden />
          ) : (
            <Muted>Aucune contrainte.</Muted>
          )}
        </Section>
        <Section icon={<ShieldCheck />} title="Comportement attendu">
          {version.expected_behavior ? <Markdown>{version.expected_behavior}</Markdown> : redacted ? <Hidden /> : <Muted>Non précisé.</Muted>}
        </Section>
      </div>

      <Section icon={<Target />} title="Résultat attendu" description="Référence utilisée par les juges ; jamais transmise à l'agent.">
        {version.expected_output !== null && version.expected_output !== undefined && version.expected_output !== "" ? (
          typeof version.expected_output === "string" ? (
            <div className="rounded-lg border border-border bg-muted/20 p-3">
              <Markdown>{version.expected_output}</Markdown>
            </div>
          ) : (
            <JsonViewer data={version.expected_output} defaultExpandDepth={2} />
          )
        ) : redacted ? (
          <Hidden />
        ) : (
          <Muted>Aucun résultat attendu.</Muted>
        )}
      </Section>

      <Section icon={<Scale />} title="Critères" description="Critères jugés pour ce scénario (sinon les critères par défaut de la configuration).">
        {version.criteria.length ? (
          <Table dense>
            <TableHeader>
              <TableRow>
                <TableHead>Critère</TableHead>
                <TableHead>Dimension</TableHead>
                <TableHead className="text-right">Poids</TableHead>
                <TableHead>Question / rubrique</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {version.criteria.map((c, i) => {
                const key = String(c.key ?? "");
                const dim = criterionDimension(key);
                return (
                  <TableRow key={`${key}-${i}`}>
                    <TableCell>
                      <span className="font-medium">{criterionName(meta, key) ?? String(c.name ?? key)}</span>
                      <span className="block font-mono text-[11px] text-muted-foreground">{key}</span>
                    </TableCell>
                    <TableCell>{dim ? <DimensionBadge dimension={dim} /> : "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{typeof c.weight === "number" ? formatNumber(c.weight) : "1"}</TableCell>
                    <TableCell className="max-w-md text-muted-foreground">
                      {c.question ? String(c.question) : criterionQuestion(meta, key) ?? "—"}
                      {c.rubric ? <span className="mt-0.5 block text-xs text-subtle-foreground">{truncate(String(c.rubric), 160)}</span> : null}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        ) : (
          <Muted>Aucun critère spécifique : les critères par défaut de la configuration d&apos;évaluation s&apos;appliquent.</Muted>
        )}
      </Section>

      <Section icon={<Ruler />} title="Règles déterministes" description={version.rules.length ? plural(version.rules.length, "règle") : undefined}>
        {version.rules.length ? <RulesTable rules={version.rules} meta={meta} /> : redacted ? <Hidden /> : <Muted>Aucune règle.</Muted>}
      </Section>

      <Section icon={<Wrench />} title="Mocks d'outils" description="Réponses simulées aux appels d'outils quand FORGE pilote la boucle d'agent.">
        {version.tool_mocks ? (
          version.tool_mocks.length ? (
            <ul className="grid gap-3">
              {version.tool_mocks.map((m, i) => (
                <li key={i} className="grid gap-2 rounded-lg border border-border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[13px] font-semibold">{String(m.tool ?? "—")}</span>
                    {m.error ? <Badge tone="red">Erreur simulée</Badge> : null}
                    {typeof m.latency_ms === "number" && m.latency_ms > 0 ? <Badge tone="neutral">{formatNumber(m.latency_ms, 0)} ms</Badge> : null}
                  </div>
                  <DetailList
                    items={[
                      { label: "Correspondance", value: m.match ? <JsonViewer data={m.match} maxHeightClassName="max-h-40" /> : "Tout appel" },
                      m.error
                        ? { label: "Erreur", value: String(m.error) }
                        : { label: "Réponse", value: <JsonViewer data={m.response ?? null} maxHeightClassName="max-h-40" /> },
                    ]}
                  />
                </li>
              ))}
            </ul>
          ) : (
            <Muted>Aucun mock d&apos;outil.</Muted>
          )
        ) : redacted ? (
          <Hidden />
        ) : (
          <Muted>Aucun mock d&apos;outil.</Muted>
        )}
      </Section>

      {showCanary && version.canary ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-wrap items-center gap-2 pt-5 text-xs text-muted-foreground">
            <EyeOff className="size-3.5" aria-hidden />
            Canari de contamination (visible des mainteneurs) :
            <span className="font-mono text-foreground">{version.canary}</span>
            <CopyButton value={version.canary} label="Copier le canari" className="size-6" />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function criterionQuestion(meta: Meta | undefined, key: string): string | undefined {
  return meta?.criteria.find((c) => c.key === key)?.question;
}

function InputView({ input }: { input: Record<string, unknown> }) {
  const prompt = typeof input.prompt === "string" ? input.prompt : null;
  const messages = Array.isArray(input.messages) ? (input.messages as Array<Record<string, unknown>>) : null;
  const rest = Object.fromEntries(Object.entries(input).filter(([k]) => k !== "prompt" && k !== "messages"));
  return (
    <div className="grid gap-3">
      {prompt ? (
        <div className="relative rounded-lg border border-border bg-muted/20 p-3 pr-10">
          <div className="absolute right-1.5 top-1.5">
            <CopyButton value={prompt} label="Copier le prompt" />
          </div>
          <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{prompt}</p>
        </div>
      ) : null}
      {messages?.length ? (
        <ol className="grid gap-2">
          {messages.map((m, i) => (
            <li key={i} className={cn("grid gap-1 rounded-lg border p-3", m.role === "assistant" ? "border-border bg-card" : "border-border bg-muted/30")}>
              <Badge tone={m.role === "assistant" ? "violet" : m.role === "system" ? "neutral" : "blue"} className="w-fit">
                {String(m.role ?? "user")}
              </Badge>
              <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{typeof m.content === "string" ? m.content : JSON.stringify(m.content)}</p>
            </li>
          ))}
        </ol>
      ) : null}
      {Object.keys(rest).length ? (
        <div className="grid gap-1.5">
          <p className="text-xs font-medium text-muted-foreground">Autres champs</p>
          <JsonViewer data={rest} />
        </div>
      ) : null}
    </div>
  );
}

function ContextView({ context }: { context: Record<string, unknown> }) {
  const documents = Array.isArray(context.documents) ? (context.documents as Array<Record<string, unknown>>) : [];
  const rest = Object.fromEntries(Object.entries(context).filter(([k]) => k !== "documents"));
  return (
    <div className="grid gap-3">
      {documents.length ? (
        <div className="grid gap-3 md:grid-cols-2">
          {documents.map((d, i) => (
            <DocumentCard key={String(d.id ?? i)} doc={d} />
          ))}
        </div>
      ) : (
        <Muted>Aucun document.</Muted>
      )}
      {Object.keys(rest).length ? <JsonViewer data={rest} /> : null}
    </div>
  );
}

function DocumentCard({ doc }: { doc: Record<string, unknown> }) {
  const [open, setOpen] = React.useState(false);
  const content = typeof doc.content === "string" ? doc.content : JSON.stringify(doc.content ?? "");
  const long = content.length > 420;
  return (
    <article className="grid content-start gap-2 rounded-lg border border-border bg-card p-3 shadow-xs">
      <header className="flex items-start justify-between gap-2">
        <div className="grid min-w-0 gap-0.5">
          <h4 className="truncate text-[13px] font-semibold">{String(doc.title ?? doc.id ?? "Document")}</h4>
          <p className="flex flex-wrap gap-x-2 font-mono text-[11px] text-muted-foreground">
            {doc.id ? <span>{String(doc.id)}</span> : null}
            {doc.source ? <span>· {String(doc.source)}</span> : null}
          </p>
        </div>
        <CopyButton value={content} label="Copier le document" />
      </header>
      <p className={cn("whitespace-pre-wrap text-[12.5px] leading-relaxed text-muted-foreground", !open && long && "line-clamp-6")}>{content}</p>
      {long ? (
        <Button type="button" variant="link" size="xs" className="w-fit" onClick={() => setOpen((o) => !o)}>
          {open ? "Réduire" : "Afficher tout"}
        </Button>
      ) : null}
    </article>
  );
}

export function RulesTable({ rules, meta }: { rules: ReadonlyArray<Record<string, unknown>>; meta: Meta | undefined }) {
  return (
    <Table dense>
      <TableHeader>
        <TableRow>
          <TableHead>Id</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Paramètres</TableHead>
          <TableHead>Critère</TableHead>
          <TableHead>Gravité</TableHead>
          <TableHead>Erreur</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rules.map((r, i) => {
          const type = String(r.type ?? "");
          const catalog = meta?.rule_types.find((t) => t.type === type);
          const criterion = typeof r.criterion_key === "string" ? r.criterion_key : catalog?.default_criterion;
          const errorType = typeof r.error_type === "string" ? r.error_type : catalog?.default_error_type;
          return (
            <TableRow key={`${String(r.id ?? i)}`}>
              <TableCell className="font-mono text-xs">
                <span className="flex items-center gap-1.5">
                  {String(r.id ?? `#${i + 1}`)}
                  {r.hidden ? (
                    <SimpleTooltip content="Règle masquée aux non-mainteneurs">
                      <span className="inline-flex">
                        <Badge tone="violet" icon={<EyeOff aria-hidden />}>
                          Masquée
                        </Badge>
                      </span>
                    </SimpleTooltip>
                  ) : null}
                </span>
              </TableCell>
              <TableCell>
                <SimpleTooltip content={catalog?.description}>
                  <span className="inline-flex">
                    <RuleTypeBadge value={type} withTooltip={false} />
                  </span>
                </SimpleTooltip>
                {r.description ? <span className="mt-0.5 block text-xs text-muted-foreground">{String(r.description)}</span> : null}
              </TableCell>
              <TableCell className="max-w-xs text-xs text-muted-foreground">
                <span className="line-clamp-2 break-words font-mono">{paramsSummary(r.params)}</span>
              </TableCell>
              <TableCell className="font-mono text-xs">
                {criterion ?? "—"}
                {typeof r.weight === "number" && r.weight !== 1 ? <span className="ml-1 text-muted-foreground">× {formatNumber(r.weight)}</span> : null}
              </TableCell>
              <TableCell>
                <SeverityBadge severity={typeof r.severity === "string" ? r.severity : "medium"} />
              </TableCell>
              <TableCell>{errorType ? <ErrorTypeBadge code={errorType} label={meta?.error_types.find((e) => e.code === errorType)?.label} /> : "—"}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
