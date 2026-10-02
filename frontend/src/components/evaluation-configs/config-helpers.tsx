"use client";

import * as React from "react";

import { SimpleTooltip } from "@/components/ui/tooltip";
import type { ForgeMeta, GateSpecValue } from "@/lib/api/evaluation-configs";
import { DIMENSION_META, DIMENSIONS, ERROR_SEVERITY_META, getMeta, isEnumValue } from "@/lib/enums";
import { formatNumber, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

export function asGate(value: Record<string, unknown>): GateSpecValue {
  const kind = String(value.kind ?? "dimension");
  return {
    id: String(value.id ?? ""),
    kind: (["dimension", "criterion", "error", "rule"].includes(kind) ? kind : "dimension") as GateSpecValue["kind"],
    target: String(value.target ?? ""),
    action: value.action === "cap" ? "cap" : "fail",
    min: typeof value.min === "number" ? value.min : null,
    min_severity: typeof value.min_severity === "string" ? value.min_severity : null,
    cap: typeof value.cap === "number" ? value.cap : null,
    description: typeof value.description === "string" ? value.description : "",
  };
}

function criterionName(key: string, meta?: ForgeMeta): string {
  return meta?.criteria.find((c) => c.key === key)?.name ?? key;
}

function errorLabel(code: string, meta?: ForgeMeta): string {
  if (code === "*") return "toute erreur";
  const label = meta?.error_types.find((e) => e.code === code)?.label;
  return label ? `une erreur « ${label} »` : `une erreur ${code}`;
}

/** Gate specification → plain French sentence (presentation only; evaluated by the API). */
export function describeGate(gate: GateSpecValue, meta?: ForgeMeta): string {
  let condition: string;
  switch (gate.kind) {
    case "dimension": {
      const label = isEnumValue(DIMENSIONS, gate.target) ? DIMENSION_META[gate.target].label : gate.target || "?";
      condition = `Si la dimension ${label} est inférieure à ${formatPercent(gate.min ?? 0)}`;
      break;
    }
    case "criterion":
      condition = `Si le critère « ${criterionName(gate.target, meta)} » est inférieur à ${formatPercent(gate.min ?? 0)}`;
      break;
    case "error": {
      const sev = gate.min_severity ? ` de gravité ${getMeta(ERROR_SEVERITY_META, gate.min_severity).label.toLowerCase()} ou plus` : "";
      condition = `Si ${errorLabel(gate.target || "*", meta)}${sev} est détectée`;
      break;
    }
    case "rule":
      condition = `Si la règle « ${gate.target || "?"} » échoue`;
      break;
    default:
      condition = "Si la condition est remplie";
  }
  const effect =
    gate.action === "cap"
      ? `le score composite est plafonné à ${formatNumber(gate.cap ?? 0, 1)} / 100`
      : "le run est invalidé (composite 0, échec de garde-fou)";
  return `${condition}, ${effect}.`;
}

/** Stacked bar of dimension weights with percentages (shares of the total). */
export function WeightsBar({ weights, className }: { weights: Record<string, number>; className?: string }) {
  const entries = DIMENSIONS.map((d) => [d, weights[d] ?? 0] as const).filter(([, w]) => w > 0);
  const total = entries.reduce((acc, [, w]) => acc + w, 0);
  if (!total) return <p className="text-[13px] text-muted-foreground">Aucune dimension pondérée.</p>;
  return (
    <div className={cn("grid gap-3", className)}>
      <div className="flex h-4 w-full overflow-hidden rounded-full bg-muted" role="img" aria-label={entries.map(([d, w]) => `${DIMENSION_META[d].label} ${formatPercent(w / total)}`).join(", ")}>
        {entries.map(([d, w]) => (
          <SimpleTooltip key={d} content={`${DIMENSION_META[d].label} : ${formatPercent(w / total, 1)}`}>
            <span
              className="h-full border-r border-card last:border-r-0"
              style={{ width: `${(w / total) * 100}%`, backgroundColor: DIMENSION_META[d].color }}
            />
          </SimpleTooltip>
        ))}
      </div>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-4">
        {entries.map(([d, w]) => (
          <li key={d} className="flex items-center gap-1.5 text-[12.5px]">
            <span className="size-2.5 shrink-0 rounded-[3px]" style={{ backgroundColor: DIMENSION_META[d].color }} aria-hidden />
            <span className="truncate text-muted-foreground">{DIMENSION_META[d].label}</span>
            <span className="ml-auto font-medium tabular-nums">{formatPercent(w / total)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export const AGGREGATION_HELP =
  "Expression sûre évaluée par critère sur les verdicts des juges : variables scores (liste 0–1), weights, confidences ; fonctions mean, median, min, max, abs, len, sum ; opérateurs + − × / , comparaisons et « a if condition else b ». Exemple : min(scores) if max(scores) - min(scores) > 0.4 else mean(scores)";

export const NORMALIZATION_FIELDS: ReadonlyArray<{ key: "cost_target" | "cost_max" | "latency_target_ms" | "latency_max_ms" | "robustness_max_std"; label: string; hint: string; step: number }> = [
  { key: "cost_target", label: "Coût cible (€)", hint: "≤ cible → score coût 1", step: 0.01 },
  { key: "cost_max", label: "Coût maximal (€)", hint: "≥ max → score coût 0", step: 0.01 },
  { key: "latency_target_ms", label: "Latence cible (ms)", hint: "≤ cible → score latence 1", step: 100 },
  { key: "latency_max_ms", label: "Latence maximale (ms)", hint: "≥ max → score latence 0", step: 100 },
  { key: "robustness_max_std", label: "Écart-type max. (robustesse)", hint: "σ des composites (0–1) ramené à 0", step: 0.01 },
];
