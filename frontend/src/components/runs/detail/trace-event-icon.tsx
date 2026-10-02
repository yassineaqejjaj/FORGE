import {
  ArrowRightLeft,
  Brain,
  Circle,
  CircleStop,
  CornerDownRight,
  Cpu,
  Database,
  Flag,
  GitBranch,
  Layers,
  MessageSquare,
  OctagonAlert,
  Play,
  Search,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { getMeta, TRACE_EVENT_TYPE_META, type Tone } from "@/lib/enums";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  run_started: Play,
  context_prepared: Layers,
  reasoning: Brain,
  message: MessageSquare,
  llm_call: Cpu,
  tool_call: Wrench,
  tool_result: CornerDownRight,
  retrieval: Search,
  memory: Database,
  agent_handoff: ArrowRightLeft,
  decision: GitBranch,
  error: OctagonAlert,
  final_answer: Flag,
  run_completed: CircleStop,
  custom: Circle,
};

export function traceEventTone(type: string, status?: string | null): Tone {
  if (status === "error") return "red";
  return getMeta(TRACE_EVENT_TYPE_META, type).tone;
}

/** Round icon chip of a trace event type (colour = type, red when the event failed). */
export function TraceEventIcon({ type, status, className }: { type: string; status?: string | null; className?: string }) {
  const Icon = ICONS[type] ?? Circle;
  const t = toneClasses(traceEventTone(type, status));
  return (
    <span
      className={cn("flex size-6 shrink-0 items-center justify-center rounded-full ring-1 ring-inset [&_svg]:size-3.5", t.soft, className)}
      aria-hidden
    >
      <Icon />
    </span>
  );
}
