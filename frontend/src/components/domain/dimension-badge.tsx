import { Badge } from "@/components/ui/badge";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { DIMENSION_META, DIMENSIONS, isEnumValue, type Dimension, type DimensionMeta } from "@/lib/enums";
import { formatScore100 } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Meta of a dimension (unknown values fall back to a neutral entry). */
export function dimensionMeta(dimension: string | null | undefined): DimensionMeta {
  if (isEnumValue(DIMENSIONS, dimension)) return DIMENSION_META[dimension];
  return { label: dimension ?? "—", short: dimension ?? "—", tone: "neutral", color: "var(--muted-foreground)" };
}

/** Stable, theme-aware colour of a dimension (CSS variable) — use for chart series and legends. */
export function dimensionColor(dimension: Dimension | string): string {
  return dimensionMeta(dimension).color;
}

/** Small colour swatch of a dimension. */
export function DimensionDot({ dimension, className }: { dimension: Dimension | string; className?: string }) {
  return (
    <span
      className={cn("inline-block size-2 shrink-0 rounded-full", className)}
      style={{ backgroundColor: dimensionColor(dimension) }}
      aria-hidden
    />
  );
}

export interface DimensionBadgeProps {
  dimension: Dimension | string;
  /** Optional dimension score on the 0–100 scale (or 0..1 with `normalized`), shown after the label. */
  score?: number | null;
  normalized?: boolean;
  /** Short label ("UX" instead of "Expérience utilisateur"). */
  short?: boolean;
  size?: "sm" | "md";
  noTooltip?: boolean;
  className?: string;
}

/** Evaluation dimension pill with its stable identity colour. */
export function DimensionBadge({ dimension, score, normalized = false, short = false, size = "sm", noTooltip = false, className }: DimensionBadgeProps) {
  const meta = dimensionMeta(dimension);
  const hasScore = typeof score === "number" && Number.isFinite(score);
  const badge = (
    <Badge tone="neutral" variant="outline" size={size} className={cn("gap-1.5", className)}>
      <DimensionDot dimension={dimension} />
      {short ? meta.short : meta.label}
      {hasScore ? (
        <span className="ml-0.5 font-semibold tabular-nums text-foreground">{formatScore100(normalized ? score * 100 : score)}</span>
      ) : null}
    </Badge>
  );
  if (noTooltip || !meta.description) return badge;
  return (
    <SimpleTooltip content={meta.description}>
      <span className="inline-flex max-w-full">{badge}</span>
    </SimpleTooltip>
  );
}
