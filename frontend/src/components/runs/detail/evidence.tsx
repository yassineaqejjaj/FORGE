"use client";

import * as React from "react";
import { FileText, Quote } from "lucide-react";

import { SimpleTooltip } from "@/components/ui/tooltip";
import type { EvidenceRef } from "@/lib/api/runs";
import { cn } from "@/lib/utils";
import { useRunDetail } from "./run-detail-context";

/** `[E12]` chip: scrolls to / highlights trace event 12 in the Run Detail timeline. */
export function EventRef({ seq, className }: { seq: number; className?: string }) {
  const ctx = useRunDetail();
  const label = ctx?.eventLabel(seq);
  const chip = (
    <span
      className={cn(
        "inline-flex h-[18px] items-center rounded border border-orange-300/70 bg-orange-50 px-1 font-mono text-[11px] font-semibold leading-none text-orange-800 dark:border-orange-400/30 dark:bg-orange-400/10 dark:text-orange-200",
        className,
      )}
    >
      E{seq}
    </span>
  );
  if (!ctx) return chip;
  return (
    <SimpleTooltip content={label ? `Événement ${seq} — ${label}` : `Aller à l'événement ${seq} de la trace`}>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          ctx.focusEvent(seq);
        }}
        className="inline-flex rounded align-baseline hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={`Aller à l'événement ${seq} de la trace${label ? ` (${label})` : ""}`}
      >
        {chip}
      </button>
    </SimpleTooltip>
  );
}

const EVENT_TOKEN = /\[E(\d+)\]/g;

/** Free text (justification, explanation) where `[E12]` references become clickable event chips. */
export function EvidenceText({ text, className }: { text: string | null | undefined; className?: string }) {
  if (!text) return null;
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(EVENT_TOKEN)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(text.slice(last, index));
    parts.push(<EventRef key={`${index}-${match[1]}`} seq={Number(match[1])} />);
    last = index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <span className={cn("whitespace-pre-line", className)}>{parts}</span>;
}

const LOCATION_LABELS: Record<string, string> = {
  output: "Sortie",
  trace: "Trace",
  input: "Entrée",
  context: "Contexte",
};

/** Evidence excerpts (output quotes or trace events). */
export function EvidenceList({ evidence, className, compact = false }: { evidence: EvidenceRef[]; className?: string; compact?: boolean }) {
  if (!evidence.length) return null;
  return (
    <ul className={cn("grid gap-1.5", className)} aria-label="Preuves">
      {evidence.map((ev, i) => (
        <li
          key={i}
          className={cn(
            "flex items-start gap-2 rounded-md border border-border bg-muted/40 text-[12.5px]",
            compact ? "px-2 py-1" : "px-2.5 py-1.5",
          )}
        >
          {typeof ev.trace_event_seq === "number" ? (
            <EventRef seq={ev.trace_event_seq} className="mt-px" />
          ) : (
            <span className="mt-0.5 flex shrink-0 items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">
              {ev.location === "output" ? <Quote className="size-3" aria-hidden /> : <FileText className="size-3" aria-hidden />}
              {LOCATION_LABELS[ev.location ?? ""] ?? ev.location ?? "Preuve"}
            </span>
          )}
          <span className="min-w-0 flex-1 break-words text-foreground/90">
            {ev.excerpt ? <EvidenceText text={ev.excerpt} /> : <span className="text-muted-foreground">Sans extrait</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}
