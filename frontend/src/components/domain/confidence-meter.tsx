import type { Tone } from "@/lib/enums";
import { formatScore } from "@/lib/format";
import { toneClasses } from "@/lib/tones";
import { cn } from "@/lib/utils";

export interface ConfidenceMeterProps {
  /** Confidence 0..1 (judge or aggregated confidence from the API). */
  value: number | null | undefined;
  /** Show the numeric value ("0,72"). Default true. */
  showValue?: boolean;
  /** Show the "Confiance" caption. */
  showLabel?: boolean;
  segments?: number;
  className?: string;
}

function toneFor(v: number): Tone {
  if (v >= 0.7) return "green";
  if (v >= 0.4) return "amber";
  return "red";
}

function qualifier(v: number): string {
  if (v >= 0.7) return "élevée";
  if (v >= 0.4) return "moyenne";
  return "faible";
}

/** Segmented confidence meter (e.g. 5 bars) for judge verdicts and aggregates. */
export function ConfidenceMeter({ value, showValue = true, showLabel = false, segments = 5, className }: ConfidenceMeterProps) {
  const valid = typeof value === "number" && Number.isFinite(value);
  const v = valid ? Math.max(0, Math.min(1, value)) : 0;
  const filled = valid ? Math.max(v > 0 ? 1 : 0, Math.round(v * segments)) : 0;
  const t = toneClasses(valid ? toneFor(v) : "neutral");
  const text = valid ? `Confiance ${qualifier(v)} (${formatScore(v)})` : "Confiance non disponible";

  return (
    <span
      className={cn("inline-flex items-center gap-1.5 text-xs", className)}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={1}
      aria-valuenow={valid ? v : undefined}
      aria-valuetext={text}
      aria-label="Confiance"
      title={text}
    >
      {showLabel ? <span className="text-muted-foreground">Confiance</span> : null}
      <span className="inline-flex items-center gap-0.5" aria-hidden>
        {Array.from({ length: segments }, (_, i) => (
          <span key={i} className={cn("h-2.5 w-1.5 rounded-[2px]", i < filled ? t.bar : t.track)} />
        ))}
      </span>
      {showValue ? <span className="font-medium tabular-nums text-foreground">{valid ? formatScore(v) : "—"}</span> : null}
    </span>
  );
}
