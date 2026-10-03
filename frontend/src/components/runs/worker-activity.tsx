"use client";

import { Cpu } from "lucide-react";

import { SimpleTooltip } from "@/components/ui/tooltip";
import { useWorkerActivity } from "@/lib/api/dashboard";
import { getMeta, JOB_QUEUE_META } from "@/lib/enums";
import { cn } from "@/lib/utils";

/**
 * Background workers' load (jobs queued / running per queue), moved here from the overview: it
 * is an operational signal for whoever launches executions, not a product indicator.
 */
export function WorkerActivityIndicator({ className }: { className?: string }) {
  const query = useWorkerActivity();
  if (!query.data) return null;
  const queues = Object.entries(query.data.queues);
  const queued = queues.reduce((n, [, q]) => n + q.queued, 0);
  const running = queues.reduce((n, [, q]) => n + q.running, 0);
  const busy = queued + running > 0;
  const detail = queues.length
    ? queues
        .map(([name, q]) => `${getMeta(JOB_QUEUE_META, name).label} : ${q.running} en cours, ${q.queued} en attente`)
        .join(" · ")
    : "Aucune tâche en file";
  const summary = busy ? `${running} en cours · ${queued} en attente` : "Workers inactifs";
  return (
    <SimpleTooltip content={detail} side="bottom" align="start">
      <span
        role="status"
        tabIndex={0}
        aria-label={`Activité des workers : ${summary}. ${detail}`}
        className={cn(
          "inline-flex h-6 items-center gap-1.5 rounded-full border border-border bg-card px-2 text-[12px] text-muted-foreground",
          className,
        )}
      >
        <Cpu className="size-3.5" aria-hidden />
        <span className={cn("size-1.5 rounded-full", busy ? "bg-blue-500" : "bg-stone-400")} aria-hidden />
        {summary}
      </span>
    </SimpleTooltip>
  );
}
