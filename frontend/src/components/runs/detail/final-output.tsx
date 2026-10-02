"use client";

import * as React from "react";
import { ChevronDown, FileText } from "lucide-react";

import { RedactedNotice } from "@/components/domain/redacted-notice";
import { Button } from "@/components/ui/button";
import { CodeBlock, CopyButton } from "@/components/ui/code-block";
import { EmptyState } from "@/components/ui/empty-state";
import { JsonViewer } from "@/components/ui/json-viewer";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { TraceSummary } from "@/lib/api/runs";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Markdown } from "./markdown";

type Mode = "rendered" | "raw" | "json";

export interface FinalOutputProps {
  trace: TraceSummary | null;
  redacted: boolean;
  /** Extra text when there is no output (failed run…). */
  emptyHint?: string;
  /** Start collapsed to this height (expand button). */
  collapsible?: boolean;
}

/** Agent final output: Markdown rendering, raw text, structured JSON; copy button. */
export function FinalOutput({ trace, redacted, emptyHint, collapsible = true }: FinalOutputProps) {
  const text = trace?.output_text ?? "";
  const json = trace?.output_json;
  const hasJson = json !== null && json !== undefined && !(typeof json === "object" && Object.keys(json as object).length === 0);
  const [mode, setMode] = React.useState<Mode>("rendered");
  const [expanded, setExpanded] = React.useState(!collapsible);
  const [overflowing, setOverflowing] = React.useState(false);
  const bodyRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const el = bodyRef.current;
    if (!el || expanded) return;
    const check = () => setOverflowing(el.scrollHeight > el.clientHeight + 4);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [expanded, mode, text]);

  if (redacted || trace?.redacted) return <RedactedNotice />;
  if (!text && !hasJson)
    return <EmptyState size="sm" icon={<FileText />} title="Aucune sortie" description={emptyHint ?? "L'agent n'a produit aucune sortie pour ce run."} />;

  const words = text ? text.trim().split(/\s+/).filter(Boolean).length : 0;
  const options = [
    { value: "rendered" as const, label: "Rendu", disabled: !text },
    { value: "raw" as const, label: "Brut", disabled: !text },
    ...(hasJson ? [{ value: "json" as const, label: "JSON structuré" }] : []),
  ];
  const current: Mode = !text && mode !== "json" ? "json" : mode;

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SegmentedControl size="sm" value={current} onValueChange={setMode} options={options} aria-label="Affichage de la sortie" />
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {text ? (
            <span className="tabular-nums">
              {formatNumber(words, 0)} mots · {formatNumber(text.length, 0)} caractères
            </span>
          ) : null}
          <CopyButton value={current === "json" ? JSON.stringify(json, null, 2) : text} label="Copier la sortie" />
        </div>
      </div>
      {current === "json" ? (
        <JsonViewer data={json} defaultExpandDepth={2} maxHeightClassName="max-h-[32rem]" />
      ) : (
        <div className="relative">
          <div ref={bodyRef} className={cn(!expanded && "max-h-[26rem] overflow-hidden")}>
            {current === "raw" ? (
              <CodeBlock code={text} wrap maxHeightClassName={expanded ? "max-h-none" : "max-h-[26rem]"} hideCopy />
            ) : (
              <div className="rounded-lg border border-border bg-background px-4 py-3">
                <Markdown>{text}</Markdown>
              </div>
            )}
          </div>
          {!expanded && overflowing ? (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 flex h-20 items-end justify-center rounded-b-lg bg-gradient-to-t from-card to-transparent pb-2">
              <Button variant="secondary" size="xs" className="pointer-events-auto" onClick={() => setExpanded(true)} rightIcon={<ChevronDown aria-hidden />}>
                Afficher toute la sortie
              </Button>
            </div>
          ) : null}
        </div>
      )}
      {hasJson && current !== "json" ? (
        <p className="text-xs text-muted-foreground">L&apos;agent a aussi renvoyé une sortie structurée (onglet « JSON structuré »).</p>
      ) : null}
    </div>
  );
}
