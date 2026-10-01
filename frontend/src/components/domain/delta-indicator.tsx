import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { formatSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * What the delta measures. Scores are better when higher; raw cost, latency and tokens are better
 * when lower. (Normalised cost / latency *dimension scores* are scores: higher is better.)
 */
export type DeltaKind = "score" | "cost" | "latency" | "tokens" | "neutral";

export interface DeltaIndicatorProps {
  /** Signed delta (candidate − baseline). */
  value: number | null | undefined;
  /** Unit appended to the number ("pts", "%", "ms", "€"…). */
  unit?: string;
  digits?: number;
  /** Semantic preset (default "score"). Overridden by `higherIsBetter`. */
  kind?: DeltaKind;
  /** Explicit direction of improvement. */
  higherIsBetter?: boolean;
  /** |value| below this is shown as neutral (no colour). Default 0 (only exact zero). */
  neutralBelow?: number;
  /** Custom number formatter (receives the signed value). */
  format?: (value: number) => string;
  size?: "sm" | "md";
  /** Hide the arrow icon. */
  hideIcon?: boolean;
  className?: string;
}

function improvesWhenHigher(kind: DeltaKind, explicit: boolean | undefined): boolean | null {
  if (typeof explicit === "boolean") return explicit;
  if (kind === "neutral") return null;
  return kind === "score";
}

/** Signed delta with an arrow; green when it is an improvement, red when it is a regression. */
export function DeltaIndicator({
  value,
  unit,
  digits = 1,
  kind = "score",
  higherIsBetter,
  neutralBelow = 0,
  format,
  size = "sm",
  hideIcon = false,
  className,
}: DeltaIndicatorProps) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return <span className={cn("text-subtle-foreground", className)}>—</span>;
  }
  const rounded = Number(value.toFixed(digits));
  const flat = rounded === 0 || Math.abs(value) < neutralBelow;
  const up = rounded > 0;
  const direction = improvesWhenHigher(kind, higherIsBetter);
  const good = flat || direction === null ? null : direction === up;
  const text = format ? format(value) : formatSigned(value, { digits, unit });
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;
  const meaning = good === null ? "" : good ? " (amélioration)" : " (dégradation)";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 whitespace-nowrap font-medium tabular-nums",
        size === "sm" ? "text-xs [&_svg]:size-3.5" : "text-sm [&_svg]:size-4",
        good === null && "text-muted-foreground",
        good === true && "text-emerald-700 dark:text-emerald-400",
        good === false && "text-red-700 dark:text-red-400",
        className,
      )}
      aria-label={`${flat ? "Stable" : up ? "Hausse" : "Baisse"} : ${text}${meaning}`}
    >
      {!hideIcon ? <Icon aria-hidden /> : null}
      <span aria-hidden>{text}</span>
    </span>
  );
}
