import { ShieldX } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { formatScore100 } from "@/lib/format";
import { SCORE_BAND_META, scoreBand, type ScoreThresholds } from "@/lib/scores";
import { cn } from "@/lib/utils";

export interface ScoreBadgeProps {
  /** Score on the 0–100 scale (composite, dimension ×100). Pass `normalized` for a 0..1 value. */
  value: number | null | undefined;
  /** Treat `value` as 0..1 and display it ×100. */
  normalized?: boolean;
  /** `run.passed` from the API (adds "Réussi" / "Échoué" to the tooltip). */
  passed?: boolean | null;
  /** `run.gate_failed` from the API (shield icon, red). */
  gateFailed?: boolean | null;
  /** Colour bands (default 80 / 65 / 50 / 35). */
  thresholds?: ScoreThresholds;
  size?: "sm" | "md" | "lg";
  /** Append the qualitative band ("Bon", "Faible"…). */
  showBand?: boolean;
  digits?: number;
  className?: string;
}

const SIZE_CLASSES = {
  sm: "",
  md: "",
  lg: "h-8 px-2.5 text-sm",
} as const;

/** Score pill on the 0–100 scale with the FORGE colour scale (green → red). */
export function ScoreBadge({
  value,
  normalized = false,
  passed,
  gateFailed,
  thresholds,
  size = "sm",
  showBand = false,
  digits = 1,
  className,
}: ScoreBadgeProps) {
  const valid = typeof value === "number" && Number.isFinite(value);
  const v100 = valid ? (normalized ? value * 100 : value) : null;
  if (v100 === null) {
    return (
      <Badge tone="neutral" size={size === "lg" ? "md" : size} variant="outline" className={cn(SIZE_CLASSES[size], className)} aria-label="Score non disponible">
        —
      </Badge>
    );
  }
  const band = scoreBand(v100, thresholds);
  const meta = SCORE_BAND_META[band];
  const tone = gateFailed ? "red" : meta.tone;
  const label = formatScore100(v100, digits);
  const tip = [
    `Score ${label} / 100 — ${meta.label}`,
    passed === true ? "Réussi" : passed === false ? "Échoué" : null,
    gateFailed ? "Garde-fou en échec" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <SimpleTooltip content={tip}>
      <span className="inline-flex">
        <Badge
          tone={tone}
          size={size === "lg" ? "md" : size}
          variant={band === "poor" || gateFailed ? "solid" : "soft"}
          icon={gateFailed ? <ShieldX aria-hidden /> : undefined}
          className={cn("font-semibold tabular-nums", SIZE_CLASSES[size], className)}
          aria-label={tip}
        >
          {label}
          {showBand ? <span className="ml-1 font-medium opacity-80">· {meta.label}</span> : null}
        </Badge>
      </span>
    </SimpleTooltip>
  );
}
