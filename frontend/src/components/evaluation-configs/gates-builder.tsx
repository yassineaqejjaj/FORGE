"use client";

import * as React from "react";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import type { ForgeMeta, GateSpecValue } from "@/lib/api/evaluation-configs";
import { DIMENSION_META, DIMENSIONS, ERROR_SEVERITIES, ERROR_SEVERITY_META, GATE_ACTION_META, GATE_ACTIONS } from "@/lib/enums";
import { describeGate } from "./config-helpers";

const KIND_OPTIONS: ReadonlyArray<{ value: GateSpecValue["kind"]; label: string; description: string }> = [
  { value: "dimension", label: "Dimension", description: "Score de dimension minimal (0–100 %)" },
  { value: "criterion", label: "Critère", description: "Score de critère minimal (0–100 %)" },
  { value: "error", label: "Erreur", description: "Type d'erreur détecté (gravité minimale)" },
  { value: "rule", label: "Règle", description: "Règle en échec (identifiant)" },
];

export function newGate(index: number): GateSpecValue {
  return { id: `gate-${index + 1}`, kind: "dimension", target: "safety", action: "fail", min: 0.5, min_severity: null, cap: null, description: "" };
}

/** Gate specification → payload (only the fields relevant to its kind and action). */
export function gatePayload(g: GateSpecValue): Record<string, unknown> {
  const out: Record<string, unknown> = { id: g.id.trim(), kind: g.kind, target: g.target.trim(), action: g.action };
  if (g.kind === "dimension" || g.kind === "criterion") out.min = g.min ?? 0;
  if (g.kind === "error" && g.min_severity) out.min_severity = g.min_severity;
  if (g.action === "cap") out.cap = g.cap ?? 0;
  if (g.description?.trim()) out.description = g.description.trim();
  return out;
}

export function gateError(g: GateSpecValue): string | null {
  if (!g.id.trim()) return "Identifiant obligatoire.";
  if (!g.target.trim()) return "Cible obligatoire.";
  if ((g.kind === "dimension" || g.kind === "criterion") && (typeof g.min !== "number" || g.min < 0 || g.min > 1)) return "Minimum entre 0 et 100 %.";
  if (g.action === "cap" && (typeof g.cap !== "number" || g.cap < 0 || g.cap > 100)) return "Plafond entre 0 et 100.";
  return null;
}

function GateRow({ gate, index, onChange, onRemove, meta, showErrors }: {
  gate: GateSpecValue;
  index: number;
  onChange: (g: GateSpecValue) => void;
  onRemove: () => void;
  meta?: ForgeMeta;
  showErrors: boolean;
}) {
  const p = `gate-${index}`;
  const set = <K extends keyof GateSpecValue>(k: K, v: GateSpecValue[K]) => onChange({ ...gate, [k]: v });
  const error = showErrors ? gateError(gate) : null;
  const targetOptions =
    gate.kind === "dimension"
      ? DIMENSIONS.map((d) => ({ value: d, label: DIMENSION_META[d].label }))
      : gate.kind === "criterion"
        ? (meta?.criteria ?? []).map((c) => ({ value: c.key, label: c.name, description: c.key }))
        : gate.kind === "error"
          ? [{ value: "*", label: "Toute erreur" }, ...(meta?.error_types ?? []).map((e) => ({ value: e.code, label: e.label, description: e.code }))]
          : null;

  return (
    <li className="grid gap-3 rounded-lg border border-border p-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field id={`${p}-id`} label="Identifiant">
          <Input id={`${p}-id`} size="sm" className="font-mono" value={gate.id} onChange={(e) => set("id", e.target.value)} />
        </Field>
        <Field id={`${p}-kind`} label="Type">
          <SimpleSelect
            id={`${p}-kind`}
            size="sm"
            value={gate.kind}
            options={KIND_OPTIONS}
            onValueChange={(kind) =>
              onChange({
                ...gate,
                kind,
                target: kind === "dimension" ? "safety" : kind === "error" ? "*" : "",
                min: kind === "dimension" || kind === "criterion" ? (gate.min ?? 0.5) : null,
                min_severity: kind === "error" ? (gate.min_severity ?? "high") : null,
              })
            }
          />
        </Field>
        <Field id={`${p}-target`} label="Cible">
          {targetOptions ? (
            <SimpleSelect id={`${p}-target`} size="sm" value={gate.target || undefined} options={targetOptions} onValueChange={(v) => set("target", v)} />
          ) : (
            <Input id={`${p}-target`} size="sm" className="font-mono" placeholder="id de la règle" value={gate.target} onChange={(e) => set("target", e.target.value)} />
          )}
        </Field>
        {gate.kind === "dimension" || gate.kind === "criterion" ? (
          <Field id={`${p}-min`} label="Minimum (%)">
            <Input
              id={`${p}-min`}
              size="sm"
              type="number"
              min={0}
              max={100}
              value={typeof gate.min === "number" ? Math.round(gate.min * 1000) / 10 : ""}
              onChange={(e) => set("min", e.target.value === "" ? null : Number(e.target.value) / 100)}
            />
          </Field>
        ) : gate.kind === "error" ? (
          <Field id={`${p}-sev`} label="Gravité minimale">
            <SimpleSelect
              id={`${p}-sev`}
              size="sm"
              value={gate.min_severity ?? "low"}
              options={ERROR_SEVERITIES.map((s) => ({ value: s, label: ERROR_SEVERITY_META[s].label }))}
              onValueChange={(v) => set("min_severity", v)}
            />
          </Field>
        ) : (
          <span />
        )}
        <Field id={`${p}-action`} label="Action">
          <SimpleSelect
            id={`${p}-action`}
            size="sm"
            value={gate.action}
            options={GATE_ACTIONS.map((a) => ({ value: a, label: GATE_ACTION_META[a].label, description: GATE_ACTION_META[a].description }))}
            onValueChange={(v) => onChange({ ...gate, action: v, cap: v === "cap" ? (gate.cap ?? 40) : null })}
          />
        </Field>
        {gate.action === "cap" ? (
          <Field id={`${p}-cap`} label="Plafond (0–100)">
            <Input
              id={`${p}-cap`}
              size="sm"
              type="number"
              min={0}
              max={100}
              value={gate.cap ?? ""}
              onChange={(e) => set("cap", e.target.value === "" ? null : Number(e.target.value))}
            />
          </Field>
        ) : null}
        <Field id={`${p}-desc`} label="Description" className={gate.action === "cap" ? "sm:col-span-2" : "sm:col-span-2 lg:col-span-3"}>
          <Input id={`${p}-desc`} size="sm" value={gate.description ?? ""} onChange={(e) => set("description", e.target.value)} />
        </Field>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] font-medium text-foreground">{describeGate(gate, meta)}</p>
        <Button variant="ghost" size="xs" leftIcon={<Trash2 aria-hidden />} onClick={onRemove} aria-label={`Supprimer le garde-fou ${gate.id}`}>
          Supprimer
        </Button>
      </div>
      {error ? <p className="text-xs font-medium text-destructive">{error}</p> : null}
    </li>
  );
}

export function GatesBuilder({ value, onChange, meta, showErrors }: { value: GateSpecValue[]; onChange: (v: GateSpecValue[]) => void; meta?: ForgeMeta; showErrors: boolean }) {
  return (
    <div className="grid gap-3">
      {value.length ? (
        <ul className="grid gap-3">
          {value.map((g, i) => (
            <GateRow
              key={i}
              index={i}
              gate={g}
              meta={meta}
              showErrors={showErrors}
              onChange={(n) => onChange(value.map((x, j) => (j === i ? n : x)))}
              onRemove={() => onChange(value.filter((_, j) => j !== i))}
            />
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted-foreground">Aucun garde-fou : le composite seul détermine la réussite.</p>
      )}
      <div>
        <Button variant="secondary" size="sm" leftIcon={<Plus aria-hidden />} onClick={() => onChange([...value, newGate(value.length)])}>
          Ajouter un garde-fou
        </Button>
      </div>
    </div>
  );
}
