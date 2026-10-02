"use client";

import * as React from "react";
import { Equal, RotateCcw } from "lucide-react";

import { DimensionDot } from "@/components/domain/dimension-badge";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { DIMENSION_META, DIMENSIONS, GROUP_DIMENSIONS, type Dimension } from "@/lib/enums";
import { formatNumber } from "@/lib/format";
import { WeightsBar } from "./config-helpers";

export type WeightPercents = Record<Dimension, number>;

/** API weights (any scale) → percentages summing to 100. */
export function toPercents(weights: Record<string, number> | undefined): WeightPercents {
  const out = Object.fromEntries(DIMENSIONS.map((d) => [d, 0])) as WeightPercents;
  const total = DIMENSIONS.reduce((acc, d) => acc + Math.max(0, weights?.[d] ?? 0), 0);
  if (!total) {
    for (const d of DIMENSIONS) out[d] = 100 / DIMENSIONS.length;
    return out;
  }
  for (const d of DIMENSIONS) out[d] = (Math.max(0, weights?.[d] ?? 0) / total) * 100;
  return out;
}

/** Percentages → API fractions (4 decimals, zero weights kept so dimensions can be excluded explicitly). */
export function toFractions(p: WeightPercents): Record<string, number> {
  return Object.fromEntries(DIMENSIONS.map((d) => [d, Math.round((p[d] / 100) * 10_000) / 10_000]));
}

/**
 * Moving one slider rebalances the others proportionally so that the total stays exactly 100 %.
 * (Form state only: the API recomputes the composite with whatever weights it receives.)
 */
function rebalance(current: WeightPercents, dim: Dimension, next: number): WeightPercents {
  const value = Math.max(0, Math.min(100, next));
  const others = DIMENSIONS.filter((d) => d !== dim);
  const othersSum = others.reduce((acc, d) => acc + current[d], 0);
  const remaining = 100 - value;
  const out = { ...current, [dim]: value } as WeightPercents;
  for (const d of others) {
    out[d] = othersSum > 0 ? (current[d] / othersSum) * remaining : remaining / others.length;
  }
  return out;
}

export function WeightsEditor({ value, onChange, initial }: { value: WeightPercents; onChange: (v: WeightPercents) => void; initial?: WeightPercents }) {
  const total = DIMENSIONS.reduce((acc, d) => acc + value[d], 0);
  return (
    <div className="grid gap-4">
      <WeightsBar weights={value} />
      <ul className="grid gap-3">
        {DIMENSIONS.map((d) => (
          <li key={d} className="grid grid-cols-[9rem_1fr_4rem] items-center gap-3">
            <span className="flex items-center gap-1.5 text-[13px]">
              <DimensionDot dimension={d} />
              {DIMENSION_META[d].label}
            </span>
            <Slider
              aria-label={`Poids ${DIMENSION_META[d].label}`}
              min={0}
              max={100}
              step={1}
              value={[Math.round(value[d] * 10) / 10]}
              onValueChange={([v]) => onChange(rebalance(value, d, v ?? 0))}
            />
            <span className="text-right text-[13px] font-medium tabular-nums">{formatNumber(value[d], 1)} %</span>
            {GROUP_DIMENSIONS.has(d) ? (
              <span className="col-span-3 -mt-2 pl-[9.75rem] text-[11px] text-muted-foreground">
                Mesurée sur les groupes de runs (benchmark, expérience) : absente du composite d&apos;un run isolé.
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
        <span className="text-[12.5px] text-muted-foreground">
          Total : <span className="font-semibold tabular-nums text-foreground">{formatNumber(total, 1)} %</span> (normalisé en
          direct)
        </span>
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="xs"
            leftIcon={<Equal aria-hidden />}
            onClick={() => onChange(Object.fromEntries(DIMENSIONS.map((d) => [d, 100 / DIMENSIONS.length])) as WeightPercents)}
          >
            Répartition égale
          </Button>
          {initial ? (
            <Button variant="ghost" size="xs" leftIcon={<RotateCcw aria-hidden />} onClick={() => onChange(initial)}>
              Rétablir
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
