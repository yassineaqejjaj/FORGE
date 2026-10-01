import { Badge } from "@/components/ui/badge";
import {
  ACTIVE_EXECUTION_STATUSES,
  ACTIVE_RUN_STATUSES,
  EXECUTION_STATUS_META,
  getMeta,
  JOB_STATUS_META,
  RUN_STATUS_META,
  type ExecutionStatus,
  type RunStatus,
} from "@/lib/enums";

export interface StatusBadgeBaseProps {
  size?: "sm" | "md";
  className?: string;
  /** Extra detail in the native tooltip (e.g. `status_detail` from the API). */
  detail?: string | null;
}

/** Run status (pending → running → evaluating → completed / failed / cancelled); pulses while active. */
export function RunStatusBadge({ status, size = "sm", className, detail }: StatusBadgeBaseProps & { status: RunStatus | string }) {
  const meta = getMeta(RUN_STATUS_META, status);
  const active = ACTIVE_RUN_STATUSES.has(status as RunStatus);
  return (
    <Badge tone={meta.tone} size={size} dot={!active} pulse={active} className={className} title={detail ?? undefined}>
      {meta.label}
    </Badge>
  );
}

/** Benchmark execution / experiment status; pulses while queued, running or aggregating. */
export function ExecutionStatusBadge({
  status,
  size = "sm",
  className,
  detail,
}: StatusBadgeBaseProps & { status: ExecutionStatus | string }) {
  const meta = getMeta(EXECUTION_STATUS_META, status);
  const active = ACTIVE_EXECUTION_STATUSES.has(status as ExecutionStatus);
  return (
    <Badge tone={meta.tone} size={size} dot={!active} pulse={active} className={className} title={detail ?? undefined}>
      {meta.label}
    </Badge>
  );
}

/** Background job status (queued / running / succeeded / failed / cancelled). */
export function JobStatusBadge({ status, size = "sm", className, detail }: StatusBadgeBaseProps & { status: string }) {
  const meta = getMeta(JOB_STATUS_META, status);
  const active = status === "running";
  return (
    <Badge tone={meta.tone} size={size} dot={!active} pulse={active} className={className} title={detail ?? undefined}>
      {meta.label}
    </Badge>
  );
}
