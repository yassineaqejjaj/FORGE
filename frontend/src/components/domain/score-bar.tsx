import type { Tone } from "@/lib/enums";
import { formatPercent, formatScore } from "@/lib/format";
import { scoreTone } from "@/lib/scores";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

export interface ScoreBarProps {
  /** Normalised criterion score (0..1 by default, see `max`). */
  value: number | null | undefined;
  max?: number;
  /** Optional label on the left (criterion name). */
  label?: string;
  showValue?: boolean;
  /** "ratio" → "0,82" (default) · "percent" → "82 %". */
  valueFormat?: "ratio" | "percent";
  /** Fixed tone; defaults to the score colour scale (green → red). */
  tone?: Tone;
  /** Draws a threshold tick (e.g. gate minimum 0,5), same unit as `value`. */
  threshold?: number;
  /** Width class of the bar track. */
  widthClassName?: string;
  /** Width class of the label column. */
  labelClassName?: string;
  size?: "sm" | "md";
  className?: string;
}

/** Compact horizontal bar for a normalised criterion score, with the FR-formatted value. */
export function ScoreBar({
  value,
  max = 1,
  label,
  showValue = true,
  valueFormat = "ratio",
  tone,
  threshold,
  widthClassName = "w-20",
  labelClassName = "w-28",
  size = "sm",
  className,
}: ScoreBarProps) {
  const valid = typeof value === "number" && Number.isFinite(value);
  const ratio = valid ? Math.max(0, Math.min(1, value / (max || 1))) : 0;
  const t = toneClasses(tone ?? (valid ? scoreTone(ratio * 100) : "neutral"));
  const thresholdRatio = typeof threshold === "number" ? Math.max(0, Math.min(1, threshold / (max || 1))) : null;
  const text = !valid ? "—" : valueFormat === "percent" ? formatPercent(ratio) : formatScore(value);

  return (
    <span className={cn("inline-flex min-w-0 items-center gap-2 text-xs", className)}>
      {label ? <span className={cn("shrink-0 truncate text-muted-foreground", labelClassName)}>{label}</span> : null}
      <span
        className={cn(
          "relative shrink-0 overflow-hidden rounded-full",
          size === "sm" ? "h-1.5" : "h-2",
          t.track,
          widthClassName,
        )}
        role="meter"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={valid ? value : undefined}
        aria-valuetext={text}
        aria-label={label ?? "Score"}
      >
        <span className={cn("absolute inset-y-0 left-0 rounded-full", t.bar)} style={{ width: `${ratio * 100}%` }} />
        {thresholdRatio !== null ? (
          <span className="absolute inset-y-0 w-px bg-foreground/60" style={{ left: `${thresholdRatio * 100}%` }} aria-hidden />
        ) : null}
      </span>
      {showValue ? (
        <span className={cn("shrink-0 text-right font-medium tabular-nums text-foreground", valueFormat === "percent" ? "w-10" : "w-8")}>
          {text}
        </span>
      ) : null}
    </span>
  );
}
