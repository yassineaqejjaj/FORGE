"use client";

import * as React from "react";
import { Bot, CircleCheck, EyeOff, Send } from "lucide-react";

import { DimensionDot, dimensionMeta } from "@/components/domain/dimension-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api/client";
import {
  useSubmitHumanEvaluation,
  type HumanEvaluation,
  type HumanEvaluationSubmitResult,
  type ReviewCriterion,
} from "@/lib/api/reviews";
import { formatNumber, formatScore100 } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Draft {
  score: number | null;
  comment: string;
}

function scaleOf(c: ReviewCriterion): { min: number; max: number } {
  return { min: c.scale_min ?? 0, max: c.scale_max ?? 5 };
}

/** AI normalised score (0..1) expressed on the criterion scale, for display next to the human rating. */
function onScale(normalized: number, c: ReviewCriterion): number {
  const { min, max } = scaleOf(c);
  return min + normalized * (max - min);
}

function ScoreChoice({
  criterion,
  value,
  onChange,
  disabled,
}: {
  criterion: ReviewCriterion;
  value: number | null;
  onChange: (v: number | null) => void;
  disabled?: boolean;
}) {
  const { min, max } = scaleOf(criterion);
  const discrete = Number.isInteger(min) && Number.isInteger(max) && max - min <= 10;
  const label = criterion.name ?? criterion.key;
  if (discrete) {
    const values = Array.from({ length: max - min + 1 }, (_, i) => min + i);
    return (
      <div role="radiogroup" aria-label={`Note pour ${label} (${min} à ${max})`} className="flex flex-wrap items-center gap-1">
        {values.map((v) => {
          const active = value === v;
          return (
            <button
              key={v}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={disabled}
              onClick={() => onChange(active ? null : v)}
              className={cn(
                "size-8 rounded-md border text-[13px] font-semibold tabular-nums transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
                active
                  ? "border-primary bg-primary text-primary-foreground shadow-xs"
                  : "border-border bg-background text-foreground hover:border-border-strong hover:bg-accent",
              )}
            >
              {v}
            </button>
          );
        })}
        {value !== null ? (
          <button type="button" onClick={() => onChange(null)} className="ml-1 text-xs text-muted-foreground hover:text-foreground hover:underline" disabled={disabled}>
            Effacer
          </button>
        ) : null}
      </div>
    );
  }
  return (
    <Input
      size="sm"
      type="number"
      className="w-28"
      min={min}
      max={max}
      step="any"
      value={value ?? ""}
      disabled={disabled}
      aria-label={`Note pour ${label} (${min} à ${max})`}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
    />
  );
}

export interface HumanEvaluationFormProps {
  runId: string;
  criteria: ReviewCriterion[];
  /** The current user's previous evaluation of this run (prefills the form; submitting replaces it). */
  existing?: HumanEvaluation[];
  /** AI normalised scores (0..1) by criterion. */
  aiScores?: Record<string, number> | null;
  /** Hide AI scores until the evaluation is submitted. */
  blind: boolean;
  onSubmitted?: (result: HumanEvaluationSubmitResult) => void;
  /** Extra actions in the footer after a successful submission (e.g. "Item suivant"). */
  afterSubmit?: React.ReactNode;
  className?: string;
}

/** Per-criterion human rating on the criterion scale + comments; blind mode hides AI scores until submitted. */
export function HumanEvaluationForm({ runId, criteria, existing = [], aiScores, blind, onSubmitted, afterSubmit, className }: HumanEvaluationFormProps) {
  const submit = useSubmitHumanEvaluation(runId);
  // Stable signature: callers may pass new arrays on every render.
  const signature = JSON.stringify([
    criteria.map((c) => c.key),
    existing.map((e) => [e.criterion_key, e.score, e.redacted ? "" : e.explanation]),
  ]);
  const initial = React.useMemo(() => {
    const d: Record<string, Draft> = {};
    for (const c of criteria) {
      const prev = existing.find((e) => e.criterion_key === c.key);
      d[c.key] = { score: prev ? prev.score : null, comment: prev && !prev.redacted ? prev.explanation : "" };
    }
    return d;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);
  const [drafts, setDrafts] = React.useState<Record<string, Draft>>(initial);
  const [comment, setComment] = React.useState("");
  const [result, setResult] = React.useState<HumanEvaluationSubmitResult | null>(null);

  const dirty = React.useRef(false);

  // New run: start over.
  React.useEffect(() => {
    dirty.current = false;
    setResult(null);
    setComment("");
  }, [runId]);

  // Prefill from the previous evaluation as it loads, unless the user already started typing.
  React.useEffect(() => {
    if (!dirty.current) setDrafts(initial);
  }, [initial]);

  const scored = criteria.filter((c) => drafts[c.key]?.score !== null && drafts[c.key]?.score !== undefined);
  const outOfScale = scored.filter((c) => {
    const v = drafts[c.key]?.score ?? 0;
    const { min, max } = scaleOf(c);
    return v < min || v > max;
  });
  const showAi = Boolean(aiScores) && (!blind || result !== null);
  const update = (key: string, patch: Partial<Draft>) => {
    dirty.current = true;
    setDrafts((prev) => ({ ...prev, [key]: { ...(prev[key] ?? { score: null, comment: "" }), ...patch } }));
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!scored.length || outOfScale.length) return;
    try {
      const res = await submit.mutateAsync({
        scores: scored.map((c) => ({
          criterion_key: c.key,
          score: drafts[c.key]!.score!,
          comment: drafts[c.key]!.comment.trim() || null,
        })),
        comment: comment.trim() || null,
      });
      setResult(res);
      onSubmitted?.(res);
    } catch {
      // rendered inline
    }
  };

  if (!criteria.length)
    return <p className="text-[13px] text-muted-foreground">Aucun critère à évaluer pour ce run.</p>;

  return (
    <form onSubmit={onSubmit} className={cn("grid gap-4", className)} aria-label="Évaluation humaine">
      {blind && !result ? (
        <Alert tone="violet" icon={<EyeOff aria-hidden />} title="Mode aveugle">
          Les scores IA sont masqués jusqu&apos;à l&apos;envoi de votre évaluation, pour ne pas influencer votre jugement.
        </Alert>
      ) : null}
      <ol className="grid gap-3">
        {criteria.map((c) => {
          const draft = drafts[c.key] ?? { score: null, comment: "" };
          const ai = aiScores?.[c.key];
          const { max } = scaleOf(c);
          const diff = result && typeof ai === "number" && draft.score !== null ? draft.score - onScale(ai, c) : null;
          return (
            <li key={c.key} className="grid gap-2 rounded-lg border border-border bg-background p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="grid min-w-0 gap-0.5">
                  <span className="flex items-center gap-1.5 text-[13px] font-semibold">
                    {c.dimension ? <DimensionDot dimension={c.dimension} /> : null}
                    {c.name ?? c.key}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    <span className="font-mono">{c.key}</span>
                    {c.dimension ? ` · ${dimensionMeta(c.dimension).label}` : ""} · échelle {formatNumber(c.scale_min ?? 0)}–{formatNumber(max)}
                  </span>
                </div>
                {showAi && typeof ai === "number" ? (
                  <Badge tone="violet" icon={<Bot aria-hidden />}>
                    IA {formatNumber(onScale(ai, c), 1)} / {formatNumber(max)}
                    {diff !== null && Math.abs(diff) >= 0.05 ? ` · écart ${diff > 0 ? "+" : "−"}${formatNumber(Math.abs(diff), 1)}` : ""}
                  </Badge>
                ) : null}
              </div>
              {c.question ? <p className="text-[13px] leading-relaxed text-foreground/90">{c.question}</p> : null}
              {c.rubric ? <p className="text-[11.5px] leading-relaxed text-muted-foreground">{c.rubric}</p> : null}
              <ScoreChoice criterion={c} value={draft.score} onChange={(score) => update(c.key, { score })} disabled={submit.isPending} />
              <Textarea
                rows={2}
                className="min-h-14 text-[13px]"
                placeholder="Commentaire (facultatif) : ce qui justifie la note…"
                value={draft.comment}
                onChange={(e) => update(c.key, { comment: e.target.value })}
                aria-label={`Commentaire pour ${c.name ?? c.key}`}
                maxLength={5000}
                disabled={submit.isPending}
              />
            </li>
          );
        })}
      </ol>
      <Textarea
        rows={2}
        placeholder="Commentaire général (facultatif)"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        aria-label="Commentaire général"
        maxLength={10000}
        disabled={submit.isPending}
      />
      {submit.isError ? (
        <Alert tone="red" title="Évaluation non enregistrée">
          {errorMessage(submit.error)}
        </Alert>
      ) : null}
      {outOfScale.length ? (
        <Alert tone="amber">Note hors échelle pour : {outOfScale.map((c) => c.name ?? c.key).join(", ")}.</Alert>
      ) : null}
      {result ? (
        <Alert tone="green" icon={<CircleCheck aria-hidden />} title="Évaluation enregistrée">
          {result.evaluations.length} critère{result.evaluations.length > 1 ? "s" : ""} noté{result.evaluations.length > 1 ? "s" : ""}.
          {result.rescored && typeof result.composite_score === "number"
            ? ` Scores du run recalculés : composite ${formatScore100(result.composite_score)} (les scores humains ne remplacent les scores IA que si la configuration le prévoit).`
            : ""}{" "}
          Votre évaluation alimente la calibration des juges.
        </Alert>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground" aria-live="polite">
          {scored.length} / {criteria.length} critère{criteria.length > 1 ? "s" : ""} noté{scored.length > 1 ? "s" : ""}
          {existing.length ? " · remplace votre évaluation précédente" : ""}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          {result ? afterSubmit : null}
          <Button type="submit" loading={submit.isPending} disabled={!scored.length || outOfScale.length > 0} leftIcon={<Send aria-hidden />}>
            {result ? "Mettre à jour" : "Enregistrer l'évaluation"}
          </Button>
        </div>
      </div>
    </form>
  );
}
