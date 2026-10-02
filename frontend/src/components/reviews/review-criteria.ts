import type { Criterion, HumanEvaluation, ReviewCriterion } from "@/lib/api/reviews";
import type { Score } from "@/lib/api/runs";

/** Dimensions measured automatically (never rated by humans nor judges — docs §7.1). */
const MEASURED_DIMENSIONS = new Set(["cost", "latency", "robustness"]);

function fromCatalog(c: Criterion): ReviewCriterion {
  return {
    key: c.key,
    dimension: c.dimension,
    name: c.name,
    question: c.question,
    rubric: c.rubric,
    scale_min: c.scale_min,
    scale_max: c.scale_max,
  };
}

/**
 * Criteria a human can rate on a run, for pages that do not come from the review queue: the criteria
 * judged on the run (AI or human scores), described by the criteria catalog; falls back to the
 * catalog's judged criteria. The API validates every submitted key and scale.
 */
export function reviewCriteriaFor(scores: Score[] | undefined, catalog: Criterion[] | undefined): ReviewCriterion[] {
  const byKey = new Map((catalog ?? []).map((c) => [c.key, c]));
  const keys = Array.from(
    new Set((scores ?? []).filter((s) => s.source === "ai" || s.source === "human").map((s) => s.criterion_key)),
  );
  const fromScores = keys
    .map((k) => {
      const c = byKey.get(k);
      if (c) return fromCatalog(c);
      const s = scores?.find((x) => x.criterion_key === k);
      return { key: k, dimension: s?.dimension ?? null, name: s?.criterion_name ?? k, scale_min: 0, scale_max: 5 } satisfies ReviewCriterion;
    })
    .filter((c) => !MEASURED_DIMENSIONS.has(String(c.dimension)));
  if (fromScores.length) return fromScores;
  return (catalog ?? []).filter((c) => c.judged && !MEASURED_DIMENSIONS.has(c.dimension)).map(fromCatalog);
}

/** AI (aggregated) normalised scores by criterion, from the run scores. */
export function aiScoresFrom(scores: Score[] | undefined): Record<string, number> {
  const out: Record<string, number> = {};
  for (const s of scores ?? []) if (s.source === "ai") out[s.criterion_key] = s.value;
  return out;
}

/** Human evaluations grouped by evaluator (user). */
export function groupByEvaluator(rows: HumanEvaluation[]): Array<{ key: string; userName: string; userId: string | null; createdAt: string; items: HumanEvaluation[] }> {
  const groups = new Map<string, { key: string; userName: string; userId: string | null; createdAt: string; items: HumanEvaluation[] }>();
  for (const r of rows) {
    const key = r.user_id ?? r.evaluator_key;
    const g = groups.get(key) ?? { key, userName: r.user_name ?? r.evaluator_key, userId: r.user_id ?? null, createdAt: r.created_at, items: [] };
    g.items.push(r);
    if (r.created_at > g.createdAt) g.createdAt = r.created_at;
    groups.set(key, g);
  }
  return [...groups.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}
