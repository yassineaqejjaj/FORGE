import { Bug } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { BUILTIN_ERROR_TYPE_META, type BuiltinErrorType, type Tone } from "@/lib/enums";

export interface ErrorTypeBadgeProps {
  /** Taxonomy code ("HALLUCINATION", or a custom code from `error_types`). */
  code: string;
  /** Label from the API (`error_types.label`) — overrides the built-in label (custom types). */
  label?: string | null;
  /** Description override (tooltip). */
  description?: string | null;
  /** Occurrence count shown after the label. */
  count?: number;
  /** Show the raw code in monospace instead of the label. */
  showCode?: boolean;
  size?: "sm" | "md";
  className?: string;
}

/** Error taxonomy badge (built-in French labels, custom types fall back to the API label or raw code). */
export function ErrorTypeBadge({ code, label, description, count, showCode = false, size = "sm", className }: ErrorTypeBadgeProps) {
  const builtin = Object.prototype.hasOwnProperty.call(BUILTIN_ERROR_TYPE_META, code)
    ? BUILTIN_ERROR_TYPE_META[code as BuiltinErrorType]
    : undefined;
  const text = showCode ? code : (label ?? builtin?.label ?? code);
  const tone: Tone = builtin?.tone ?? "neutral";
  const tip = description ?? builtin?.description;
  const badge = (
    <Badge tone={tone} size={size} mono={showCode} icon={<Bug aria-hidden />} className={className}>
      {text}
      {typeof count === "number" ? <span className="ml-1 font-semibold tabular-nums opacity-80">× {count}</span> : null}
    </Badge>
  );
  return (
    <SimpleTooltip content={tip ? `${code} — ${tip}` : code}>
      <span className="inline-flex max-w-full">
        {badge}
      </span>
    </SimpleTooltip>
  );
}
