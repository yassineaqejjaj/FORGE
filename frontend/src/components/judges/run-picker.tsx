"use client";

import * as React from "react";
import { Search } from "lucide-react";

import { ScoreBadge } from "@/components/domain/score-badge";
import { RunStatusBadge } from "@/components/domain/status-badge";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useRunsList, type RunListItem } from "@/lib/api/benchmarks";
import { formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface RunPickerProps {
  /** Single selection (radio) or multiple (checkboxes). */
  mode: "single" | "multiple";
  value: string[];
  onChange: (ids: string[], runs: RunListItem[]) => void;
  /** Restrict to terminal runs (default: completed). */
  status?: string;
  className?: string;
  max?: number;
}

/** Searchable list of recent runs (`GET /runs`). */
export function RunPicker({ mode, value, onChange, status = "completed", className, max = 500 }: RunPickerProps) {
  const [q, setQ] = React.useState("");
  const debounced = useDebouncedValue(q, 250);
  const runs = useRunsList({ status, q: debounced || undefined, page_size: 30, sort: "-created_at" });
  const selected = new Set(value);
  const known = React.useRef(new Map<string, RunListItem>());
  for (const r of runs.data?.items ?? []) known.current.set(r.id, r);

  const toggle = (r: RunListItem) => {
    let next: string[];
    if (mode === "single") next = [r.id];
    else if (selected.has(r.id)) next = value.filter((v) => v !== r.id);
    else next = value.length >= max ? value : [...value, r.id];
    onChange(
      next,
      next.map((id) => known.current.get(id)).filter((x): x is RunListItem => Boolean(x)),
    );
  };

  return (
    <div className={cn("grid gap-2", className)}>
      <Input
        size="sm"
        leftIcon={<Search aria-hidden />}
        placeholder="Rechercher par scénario ou agent…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        aria-label="Rechercher un run"
      />
      <div className="max-h-72 overflow-y-auto rounded-md border border-border">
        {runs.isPending ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : !runs.data?.items.length ? (
          <p className="px-3 py-6 text-center text-[13px] text-muted-foreground">Aucun run terminé.</p>
        ) : (
          <ul role="listbox" aria-multiselectable={mode === "multiple"} aria-label="Runs">
            {runs.data.items.map((r) => {
              const isSel = selected.has(r.id);
              return (
                <li key={r.id} role="option" aria-selected={isSel}>
                  <label
                    className={cn(
                      "flex cursor-pointer items-center gap-2 border-b border-border px-3 py-2 text-[13px] last:border-b-0 hover:bg-muted/60",
                      isSel && "bg-brand-soft/50",
                    )}
                  >
                    {mode === "multiple" ? (
                      <Checkbox checked={isSel} onCheckedChange={() => toggle(r)} />
                    ) : (
                      <input
                        type="radio"
                        name="run-picker"
                        className="size-3.5 accent-[var(--primary)]"
                        checked={isSel}
                        onChange={() => toggle(r)}
                      />
                    )}
                    <VisibilityBadge visibility={r.visibility} iconOnly />
                    <span className="grid min-w-0 flex-1">
                      <span className="truncate font-medium">{r.scenario_name}</span>
                      <span className="truncate text-xs text-muted-foreground">
                        {r.agent_label ?? r.agent_name} · {formatDateTime(r.created_at)} · {shortId(r.id)}
                      </span>
                    </span>
                    <RunStatusBadge status={r.status} />
                    <ScoreBadge value={r.composite_score} passed={r.passed} gateFailed={r.gate_failed} />
                  </label>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {mode === "multiple" ? <p className="text-xs text-muted-foreground">{value.length} run(s) sélectionné(s)</p> : null}
    </div>
  );
}
