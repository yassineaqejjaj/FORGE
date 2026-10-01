import { Badge } from "@/components/ui/badge";
import { ERROR_SEVERITY_META, getMeta, SEVERITY_RANK, type ErrorSeverity } from "@/lib/enums";
import { cn } from "@/lib/utils";

export interface SeverityBadgeProps {
  severity: ErrorSeverity | string | null | undefined;
  size?: "sm" | "md";
  /** Prefix the label with "Gravité". */
  withPrefix?: boolean;
  className?: string;
}

/** Signal-strength glyph: 1 to 4 filled bars (never colour alone). */
function SeverityBars({ rank }: { rank: number }) {
  return (
    <span className="inline-flex h-2.5 items-end gap-px" aria-hidden>
      {[0, 1, 2, 3].map((i) => (
        <span
          key={i}
          className={cn("w-[2px] rounded-[1px] bg-current", i > rank && "opacity-25")}
          style={{ height: `${40 + i * 20}%` }}
        />
      ))}
    </span>
  );
}

/** Error severity: low (neutral) · medium (amber) · high (orange) · critical (solid red). */
export function SeverityBadge({ severity, size = "sm", withPrefix = false, className }: SeverityBadgeProps) {
  const meta = getMeta(ERROR_SEVERITY_META, severity);
  const rank = severity && severity in SEVERITY_RANK ? SEVERITY_RANK[severity as ErrorSeverity] : 0;
  return (
    <Badge
      tone={meta.tone}
      size={size}
      variant={severity === "critical" ? "solid" : "soft"}
      icon={<SeverityBars rank={rank} />}
      className={className}
      aria-label={`Gravité ${meta.label.toLowerCase()}`}
    >
      {withPrefix ? `Gravité ${meta.label.toLowerCase()}` : meta.label}
    </Badge>
  );
}
