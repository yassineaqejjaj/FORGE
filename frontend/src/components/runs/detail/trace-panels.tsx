"use client";

import * as React from "react";
import { Bot, ChevronRight, Cpu, MessageSquare, Settings2, User, Wrench } from "lucide-react";

import { CostDisplay, DurationDisplay, TokenCount } from "@/components/domain/metric-display";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { Badge } from "@/components/ui/badge";
import { CodeBlock } from "@/components/ui/code-block";
import { EmptyState } from "@/components/ui/empty-state";
import { JsonViewer } from "@/components/ui/json-viewer";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { TraceMessage, TraceModelCall, TraceToolCall } from "@/lib/api/runs";
import { formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";
import { EventRef } from "./evidence";
import { Markdown } from "./markdown";

const ROLE_META: Record<string, { label: string; icon: React.ReactNode; className: string }> = {
  system: { label: "Système", icon: <Settings2 aria-hidden />, className: "bg-muted/60" },
  user: { label: "Utilisateur", icon: <User aria-hidden />, className: "bg-blue-50/60 dark:bg-blue-400/5" },
  assistant: { label: "Agent", icon: <Bot aria-hidden />, className: "bg-card" },
  tool: { label: "Outil", icon: <Wrench aria-hidden />, className: "bg-amber-50/50 dark:bg-amber-400/5" },
};

function Content({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return <p className="text-xs text-muted-foreground">Contenu vide.</p>;
  if (typeof value === "string") return <Markdown className="text-[13px]">{value}</Markdown>;
  return <JsonViewer data={value} defaultExpandDepth={1} maxHeightClassName="max-h-72" />;
}

/** Conversation derived from the trace (`message` / `final_answer` events, or the agent-reported messages). */
export function MessagesPanel({ messages, redacted }: { messages: TraceMessage[]; redacted: boolean }) {
  if (redacted) return <RedactedNotice />;
  if (!messages.length)
    return <EmptyState size="sm" icon={<MessageSquare />} title="Aucun message" description="L'agent n'a rapporté aucun message dans sa trace." />;
  return (
    <ol className="grid gap-2.5">
      {messages.map((m, i) => {
        const role = ROLE_META[m.role ?? ""] ?? { label: m.role ?? "Message", icon: <MessageSquare aria-hidden />, className: "bg-card" };
        return (
          <li key={`${m.seq ?? "m"}-${i}`} className={cn("rounded-lg border border-border px-3.5 py-2.5", role.className)}>
            <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground [&_svg]:size-3.5">
              {role.icon}
              <span className="font-medium text-foreground">{role.label}</span>
              {m.name ? <span className="font-mono">{m.name}</span> : null}
              {typeof m.seq === "number" ? <EventRef seq={m.seq} /> : null}
              {typeof m.offset_ms === "number" ? <span className="ml-auto tabular-nums">+{formatMs(m.offset_ms)}</span> : null}
            </div>
            {m.redacted ? <RedactedNotice variant="inline" /> : <Content value={m.content} />}
          </li>
        );
      })}
    </ol>
  );
}

function ToolCallRow({ call }: { call: TraceToolCall }) {
  const [open, setOpen] = React.useState(false);
  return (
    <li className="rounded-lg border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronRight className={cn("size-4 shrink-0 text-subtle-foreground transition-transform", open && "rotate-90")} aria-hidden />
        <Wrench className="size-3.5 shrink-0 text-orange-600 dark:text-orange-400" aria-hidden />
        <span className="truncate font-mono font-medium">{call.tool}</span>
        <Badge tone={call.status === "error" ? "red" : "green"} dot>
          {call.status === "error" ? "Erreur" : "OK"}
        </Badge>
        <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <span className="tabular-nums">+{formatMs(call.offset_ms)}</span>
          <DurationDisplay ms={call.duration_ms} />
        </span>
      </button>
      {open ? (
        <div className="grid gap-3 border-t border-border px-3 py-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            Appel <EventRef seq={call.seq} />
            {call.result_seq ? (
              <>
                · Résultat <EventRef seq={call.result_seq} />
              </>
            ) : null}
          </div>
          {call.redacted ? (
            <RedactedNotice variant="inline" />
          ) : (
            <>
              <div className="grid gap-1">
                <h4 className="text-[11px] font-semibold uppercase tracking-wide text-subtle-foreground">Arguments</h4>
                {typeof call.arguments === "string" ? (
                  <CodeBlock code={call.arguments} wrap maxHeightClassName="max-h-60" />
                ) : (
                  <JsonViewer data={call.arguments ?? null} defaultExpandDepth={2} maxHeightClassName="max-h-60" />
                )}
              </div>
              <div className="grid gap-1">
                <h4 className="text-[11px] font-semibold uppercase tracking-wide text-subtle-foreground">Résultat</h4>
                {typeof call.result === "string" ? (
                  <CodeBlock code={call.result} wrap maxHeightClassName="max-h-60" />
                ) : (
                  <JsonViewer data={call.result ?? null} defaultExpandDepth={2} maxHeightClassName="max-h-60" />
                )}
              </div>
            </>
          )}
        </div>
      ) : null}
    </li>
  );
}

/** Tool calls with their arguments and results. */
export function ToolCallsPanel({ calls }: { calls: TraceToolCall[] }) {
  if (!calls.length)
    return <EmptyState size="sm" icon={<Wrench />} title="Aucun appel d'outil" description="L'agent n'a appelé aucun outil pendant ce run." />;
  return (
    <ul className="grid gap-2">
      {calls.map((c) => (
        <ToolCallRow key={c.seq} call={c} />
      ))}
    </ul>
  );
}

/** LLM calls of the agent (model, tokens, cost, duration). */
export function ModelCallsPanel({ calls }: { calls: TraceModelCall[] }) {
  if (!calls.length)
    return <EmptyState size="sm" icon={<Cpu />} title="Aucun appel de modèle rapporté" description="L'agent n'a rapporté aucun appel LLM dans sa trace." />;
  return (
    <Table dense containerClassName="rounded-lg border border-border">
      <TableHeader>
        <TableRow>
          <TableHead>Événement</TableHead>
          <TableHead>Modèle</TableHead>
          <TableHead className="text-right">Tokens</TableHead>
          <TableHead className="text-right">Coût</TableHead>
          <TableHead className="text-right">Durée</TableHead>
          <TableHead>Statut</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {calls.map((c) => (
          <TableRow key={c.seq}>
            <TableCell>
              <EventRef seq={c.seq} />
            </TableCell>
            <TableCell className="font-mono text-xs">{c.model ?? "—"}</TableCell>
            <TableCell className="text-right">
              <TokenCount input={c.input_tokens} output={c.output_tokens} />
            </TableCell>
            <TableCell className="text-right">
              <CostDisplay value={c.cost} />
            </TableCell>
            <TableCell className="text-right">
              <DurationDisplay ms={c.duration_ms} />
            </TableCell>
            <TableCell>
              <Badge tone={c.status === "error" ? "red" : "green"} dot>
                {c.status === "error" ? "Erreur" : "OK"}
              </Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
