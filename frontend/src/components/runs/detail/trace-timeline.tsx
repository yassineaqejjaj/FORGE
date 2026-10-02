"use client";

import * as React from "react";
import { Coins, Cpu, Hash, Timer, TriangleAlert, Wrench } from "lucide-react";

import { CostDisplay, DurationDisplay, TokenCount } from "@/components/domain/metric-display";
import { Badge } from "@/components/ui/badge";
import { SimpleTooltip } from "@/components/ui/tooltip";
import type { RunTimeline, TimelineItem } from "@/lib/api/runs";
import { getMeta, TRACE_EVENT_TYPE_META } from "@/lib/enums";
import { formatMs, formatNumber, formatPercent } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";
import { useRunDetail } from "./run-detail-context";
import { TraceEventIcon, traceEventTone } from "./trace-event-icon";

export const eventAnchorId = (seq: number) => `run-event-${seq}`;

function Chip({ icon, children, title }: { icon?: React.ReactNode; children: React.ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex h-5 max-w-full items-center gap-1 rounded border border-border bg-background px-1.5 text-[11px] text-muted-foreground [&_svg]:size-3 [&_svg]:shrink-0"
    >
      {icon}
      <span className="truncate">{children}</span>
    </span>
  );
}

/** Time split by event type (stacked bar + legend), from `timeline.by_type`. */
function TimeBreakdown({ timeline }: { timeline: RunTimeline }) {
  const rows = (timeline.by_type ?? []).filter((r) => r.share > 0.001);
  if (!rows.length) return null;
  return (
    <div className="grid gap-1.5">
      <div className="flex h-2 w-full gap-[2px] overflow-hidden rounded-full bg-muted" role="img" aria-label={`Répartition du temps : ${rows.map((r) => `${r.label} ${formatPercent(r.share)}`).join(", ")}`}>
        {rows.map((r) => (
          <span
            key={r.type}
            className={cn("h-full first:rounded-l-full last:rounded-r-full", toneClasses(traceEventTone(r.type)).bar)}
            style={{ width: `${r.share * 100}%` }}
            title={`${r.label} : ${formatPercent(r.share)} · ${formatMs(r.total_duration_ms)}`}
          />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        {rows.map((r) => (
          <li key={r.type} className="flex items-center gap-1">
            <span className={cn("size-2 rounded-[2px]", toneClasses(traceEventTone(r.type)).dot)} aria-hidden />
            {r.label}
            <span className="font-medium tabular-nums text-foreground">{formatPercent(r.share)}</span>
            <span className="tabular-nums">({r.count})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TimelineRow({
  item,
  total,
  highlighted,
  onOpen,
}: {
  item: TimelineItem;
  total: number;
  highlighted: boolean;
  onOpen: (seq: number) => void;
}) {
  const meta = getMeta(TRACE_EVENT_TYPE_META, item.type);
  const error = item.status === "error";
  const left = total > 0 ? Math.min(100, (item.offset_ms / total) * 100) : 0;
  const width = total > 0 && item.duration_ms ? Math.max(0.6, Math.min(100 - left, (item.duration_ms / total) * 100)) : 0.6;
  const tone = toneClasses(traceEventTone(item.type, item.status));
  return (
    <li id={eventAnchorId(item.seq)} className="relative scroll-mt-24">
      <button
        type="button"
        onClick={() => onOpen(item.seq)}
        className={cn(
          "group grid w-full grid-cols-[3.5rem_minmax(0,1fr)] gap-x-2 rounded-lg px-2 py-2 text-left transition-colors",
          "hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          highlighted && "bg-brand-soft ring-2 ring-brand/60",
          error && !highlighted && "bg-red-50/60 dark:bg-red-400/5",
        )}
        aria-label={`Événement ${item.seq} à ${item.offset_label} : ${meta.label} — ${item.name}${error ? " (erreur)" : ""}. Ouvrir le détail`}
      >
        <span className="pt-1 font-mono text-[11.5px] tabular-nums text-muted-foreground">{item.offset_label}</span>
        <span className="flex min-w-0 gap-2.5" style={{ paddingLeft: `${Math.min(item.depth, 6) * 16}px` }}>
          <TraceEventIcon type={item.type} status={item.status} className="mt-0.5" />
          <span className="grid min-w-0 flex-1 gap-1">
            <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className="truncate text-[13px] font-medium text-foreground">{item.name || item.label}</span>
              <span className={cn("text-[11px] font-medium", tone.text)}>{meta.label}</span>
              {error ? (
                <Badge tone="red" variant="solid" icon={<TriangleAlert aria-hidden />}>
                  Erreur
                </Badge>
              ) : null}
              <span className="ml-auto flex items-center gap-2 text-[11px] text-muted-foreground">
                <span className="font-mono text-subtle-foreground">E{item.seq}</span>
                {item.duration_ms ? <DurationDisplay ms={item.duration_ms} className="font-medium text-foreground" /> : null}
              </span>
            </span>
            {item.summary && item.summary !== item.name ? (
              <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{item.summary}</span>
            ) : null}
            {item.model || item.tool || item.agent || item.tokens || item.cost ? (
              <span className="flex flex-wrap gap-1">
                {item.model ? <Chip icon={<Cpu aria-hidden />} title="Modèle">{item.model}</Chip> : null}
                {item.tool ? <Chip icon={<Wrench aria-hidden />} title="Outil">{item.tool}</Chip> : null}
                {item.agent && item.type !== "run_started" ? <Chip title="Agent">{item.agent}</Chip> : null}
                {item.tokens ? (
                  <Chip icon={<Hash aria-hidden />} title="Tokens">
                    <TokenCount total={item.tokens} input={item.input_tokens} output={item.output_tokens} />
                  </Chip>
                ) : null}
                {item.cost ? (
                  <Chip icon={<Coins aria-hidden />} title="Coût">
                    <CostDisplay value={item.cost} />
                  </Chip>
                ) : null}
              </span>
            ) : null}
            <span className="relative mt-0.5 h-1 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
              <span className={cn("absolute inset-y-0 rounded-full", tone.bar)} style={{ left: `${left}%`, width: `${width}%` }} />
            </span>
          </span>
        </span>
      </button>
    </li>
  );
}

export interface TraceTimelineProps {
  timeline: RunTimeline;
  onOpenEvent: (seq: number) => void;
  /** Selected event (drawer open). */
  selectedSeq?: number | null;
}

/** Execution trace as a timeline: offsets, type icons, nesting, durations (gantt bar), chips, errors. */
export function TraceTimeline({ timeline, onOpenEvent, selectedSeq }: TraceTimelineProps) {
  const ctx = useRunDetail();
  const highlighted = ctx?.highlightedSeq ?? null;
  const nonce = ctx?.focusNonce ?? 0;
  const items = timeline.items;
  const total = timeline.total_duration_ms ?? Math.max(0, ...items.map((i) => i.offset_ms + (i.duration_ms ?? 0)));

  React.useEffect(() => {
    if (highlighted === null) return;
    const el = document.getElementById(eventAnchorId(highlighted));
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    el.querySelector("button")?.focus({ preventScroll: true });
  }, [highlighted, nonce]);

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap gap-1.5">
        <Chip icon={<Timer aria-hidden />} title="Durée totale de la trace">{formatMs(total)}</Chip>
        <Chip title="Événements">{formatNumber(items.length, 0)} événements</Chip>
        <Chip icon={<Cpu aria-hidden />} title="Appels LLM">{formatNumber(timeline.llm_calls ?? 0, 0)} appels LLM</Chip>
        <Chip icon={<Wrench aria-hidden />} title="Appels d'outils">{formatNumber(timeline.tool_calls ?? 0, 0)} outils</Chip>
        {timeline.errors ? (
          <Badge tone="red" icon={<TriangleAlert aria-hidden />}>
            {timeline.errors} erreur{timeline.errors > 1 ? "s" : ""}
          </Badge>
        ) : null}
        {timeline.input_tokens || timeline.output_tokens ? (
          <Chip icon={<Hash aria-hidden />} title="Tokens">
            <TokenCount input={timeline.input_tokens} output={timeline.output_tokens} />
          </Chip>
        ) : null}
        {timeline.cost ? (
          <Chip icon={<Coins aria-hidden />} title="Coût">
            <CostDisplay value={timeline.cost} />
          </Chip>
        ) : null}
      </div>
      <TimeBreakdown timeline={timeline} />
      {timeline.slowest_steps?.length ? (
        <p className="text-xs text-muted-foreground">
          Étape la plus longue :{" "}
          <SimpleTooltip content="Mettre en évidence dans la trace">
            <button
              type="button"
              className="font-medium text-foreground underline-offset-2 hover:underline"
              onClick={() => ctx?.focusEvent(timeline.slowest_steps![0]!.seq)}
            >
              {timeline.slowest_steps[0]!.label}
            </button>
          </SimpleTooltip>{" "}
          ({formatMs(timeline.slowest_steps[0]!.duration_ms)}, {formatPercent(timeline.slowest_steps[0]!.share)} du temps)
        </p>
      ) : null}
      <ol className="relative -mx-2 grid gap-0.5" aria-label="Événements de la trace">
        {items.map((item) => (
          <TimelineRow
            key={item.seq}
            item={item}
            total={total}
            highlighted={highlighted === item.seq || selectedSeq === item.seq}
            onOpen={onOpenEvent}
          />
        ))}
      </ol>
    </div>
  );
}
