/**
 * Presentation scale for scores (colour bands only). Pass/fail, gates, verdicts and composites are
 * always computed by the API (`run.passed`, `run.gate_failed`, `comparison.verdict`…): this module
 * never decides anything, it only maps a number to a colour and a French qualifier.
 */
import type { Tone } from "@/lib/enums";

export interface ScoreThresholds {
  /** ≥ excellent → green. */
  excellent: number;
  /** ≥ good → teal. */
  good: number;
  /** ≥ fair → amber. */
  fair: number;
  /** ≥ weak → orange; below → red. */
  weak: number;
}

/** Default bands on the 0–100 scale. */
export const DEFAULT_SCORE_THRESHOLDS: ScoreThresholds = { excellent: 80, good: 65, fair: 50, weak: 35 };

export type ScoreBand = "excellent" | "good" | "fair" | "weak" | "poor";

export const SCORE_BAND_META: Record<ScoreBand, { label: string; tone: Tone }> = {
  excellent: { label: "Excellent", tone: "green" },
  good: { label: "Bon", tone: "teal" },
  fair: { label: "Moyen", tone: "amber" },
  weak: { label: "Faible", tone: "orange" },
  poor: { label: "Critique", tone: "red" },
};

/** Band of a 0–100 score. */
export function scoreBand(value100: number, thresholds: ScoreThresholds = DEFAULT_SCORE_THRESHOLDS): ScoreBand {
  if (value100 >= thresholds.excellent) return "excellent";
  if (value100 >= thresholds.good) return "good";
  if (value100 >= thresholds.fair) return "fair";
  if (value100 >= thresholds.weak) return "weak";
  return "poor";
}

/** Tone of a 0–100 score (neutral when missing). */
export function scoreTone(value100: number | null | undefined, thresholds?: ScoreThresholds): Tone {
  if (typeof value100 !== "number" || !Number.isFinite(value100)) return "neutral";
  return SCORE_BAND_META[scoreBand(value100, thresholds)].tone;
}

/** Clamp to [0, 100]. */
export function clamp100(value: number): number {
  return Math.max(0, Math.min(100, value));
}
