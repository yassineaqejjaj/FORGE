"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { TraceEventSourceBadge } from "@/components/domain/enum-badge";
import { DurationDisplay } from "@/components/domain/metric-display";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CodeBlock } from "@/components/ui/code-block";
import { JsonViewer } from "@/components/ui/json-viewer";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import type { TimelineItem, TraceEvent } from "@/lib/api/runs";
import { getMeta, TRACE_EVENT_TYPE_META } from "@/lib/enums";
import { formatDateTimePrecise, formatMs } from "@/lib/format";
import { TraceEventIcon } from "./trace-event-icon";

function Payload({ title, value }: { title: string; value: unknown }) {
  if (value === null || value === undefined || value === "") {
    return (
      <section className="grid gap-1.5">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">{title}</h3>
        <p className="text-[13px] text-muted-foreground">Aucune donnée.</p>
      </section>
    );
  }
  return (
    <section className="grid gap-1.5">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">{title}</h3>
      {typeof value === "string" ? (
        <CodeBlock code={value} wrap maxHeightClassName="max-h-80" />
      ) : (
        <JsonViewer data={value} defaultExpandDepth={2} maxHeightClassName="max-h-80" />
      )}
    </section>
  );
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-[13px] text-foreground">{children}</dd>
    </div>
  );
}

export interface EventDrawerProps {
  seq: number | null;
  onSeqChange: (seq: number | null) => void;
  events: TraceEvent[] | undefined;
  items: TimelineItem[];
  loading: boolean;
}

/** Detail drawer of a trace event: timing, source, input / output / attributes JSON. */
export function EventDrawer({ seq, onSeqChange, events, items, loading }: EventDrawerProps) {
  const event = seq === null ? undefined : events?.find((e) => e.seq === seq);
  const item = seq === null ? undefined : items.find((i) => i.seq === seq);
  const meta = getMeta(TRACE_EVENT_TYPE_META, event?.type ?? item?.type);
  const seqs = items.map((i) => i.seq);
  const index = seq === null ? -1 : seqs.indexOf(seq);
  const prev = index > 0 ? seqs[index - 1] : undefined;
  const next = index >= 0 && index < seqs.length - 1 ? seqs[index + 1] : undefined;
  const parent = event?.parent_id ? events?.find((e) => e.id === event.parent_id) : undefined;

  return (
    <Sheet open={seq !== null} onOpenChange={(o) => !o && onSeqChange(null)}>
      <SheetContent size="lg" aria-describedby={undefined}>
        <SheetHeader>
          <div className="flex items-center gap-2.5">
            <TraceEventIcon type={event?.type ?? item?.type ?? "custom"} status={event?.status ?? item?.status} />
            <div className="grid min-w-0">
              <SheetTitle className="truncate">{event?.name ?? item?.name ?? "Événement"}</SheetTitle>
              <SheetDescription className="text-xs">
                E{seq} · {meta.label} · {item?.offset_label ?? (event ? formatMs(event.offset_ms) : "—")}
              </SheetDescription>
            </div>
          </div>
          <div className="mt-2 flex items-center gap-1">
            <Button variant="ghost" size="xs" disabled={prev === undefined} onClick={() => prev !== undefined && onSeqChange(prev)} leftIcon={<ChevronLeft aria-hidden />}>
              Précédent
            </Button>
            <Button variant="ghost" size="xs" disabled={next === undefined} onClick={() => next !== undefined && onSeqChange(next)} rightIcon={<ChevronRight aria-hidden />}>
              Suivant
            </Button>
          </div>
        </SheetHeader>
        <SheetBody className="grid content-start gap-5">
          {loading && !event ? (
            <div className="grid gap-3">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : !event ? (
            <p className="text-sm text-muted-foreground">Événement introuvable dans la trace.</p>
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Meta label="Statut">
                  <Badge tone={event.status === "error" ? "red" : "green"} dot>
                    {event.status === "error" ? "Erreur" : "OK"}
                  </Badge>
                </Meta>
                <Meta label="Source">
                  <TraceEventSourceBadge value={event.source} />
                </Meta>
                <Meta label="Durée">
                  <DurationDisplay ms={event.duration_ms} />
                </Meta>
                <Meta label="Décalage">{formatMs(event.offset_ms)}</Meta>
                <Meta label="Début">{formatDateTimePrecise(event.started_at)}</Meta>
                <Meta label="Fin">{formatDateTimePrecise(event.ended_at)}</Meta>
                {parent ? (
                  <Meta label="Parent">
                    <button type="button" className="text-primary hover:underline" onClick={() => onSeqChange(parent.seq)}>
                      E{parent.seq} · {parent.name}
                    </button>
                  </Meta>
                ) : null}
                {event.span_id ? <Meta label="Span">{<span className="font-mono text-xs">{event.span_id}</span>}</Meta> : null}
              </dl>
              {item?.summary ? <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-[13px] leading-relaxed">{item.summary}</p> : null}
              {event.redacted ? (
                <RedactedNotice description="Les entrées, sorties et attributs de cet événement appartiennent à un scénario privé : ils sont réservés aux mainteneurs." />
              ) : (
                <>
                  <Payload title="Entrée" value={event.input} />
                  <Payload title="Sortie" value={event.output} />
                  <Payload title="Attributs" value={event.attributes && Object.keys(event.attributes).length ? event.attributes : null} />
                </>
              )}
            </>
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}
