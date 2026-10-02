"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, Braces, EyeOff, Plus, Trash2 } from "lucide-react";

import { fieldError, errorsUnder } from "@/components/agents/kit/field-errors";
import { JsonField, parseJsonText, toJsonText } from "@/components/agents/kit/json-field";
import { TagInput } from "@/components/agents/kit/tag-input";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { ApiFieldError } from "@/lib/api/types";
import type { Meta, MetaRuleType } from "@/lib/api/scenarios";
import { ERROR_SEVERITIES, ERROR_SEVERITY_META, getMeta, PII_TYPE_META, type ErrorSeverity } from "@/lib/enums";
import { cn } from "@/lib/utils";

import { newRule, type RuleRow } from "./editor-model";

interface JsonSchemaProp {
  type?: string | string[];
  enum?: unknown[];
  items?: { type?: string; enum?: unknown[] };
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
}

const DEFAULT = "__default__";

function propsOf(rt: MetaRuleType | undefined): Array<[string, JsonSchemaProp]> {
  const props = rt?.params_schema?.properties;
  if (!props || typeof props !== "object") return [];
  return Object.entries(props as Record<string, JsonSchemaProp>);
}

function requiredOf(rt: MetaRuleType | undefined): string[] {
  const r = rt?.params_schema?.required;
  return Array.isArray(r) ? r.map(String) : [];
}

function enumLabel(value: string): string {
  if (value in PII_TYPE_META) return PII_TYPE_META[value as keyof typeof PII_TYPE_META].label;
  if (value === "all") return "Tous (all)";
  if (value === "any") return "Au moins un (any)";
  return value;
}

/** Params form generated from the rule type's JSON schema (`/meta` catalog), JSON fallback for complex values. */
function ParamsForm({
  rule,
  ruleType,
  onChange,
  idPrefix,
  error,
}: {
  rule: RuleRow;
  ruleType: MetaRuleType | undefined;
  onChange: (rule: RuleRow) => void;
  idPrefix: string;
  error?: string;
}) {
  const props = propsOf(ruleType);
  const required = requiredOf(ruleType);
  const setParam = (key: string, value: unknown) => {
    const params = { ...rule.params };
    if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) delete params[key];
    else params[key] = value;
    onChange({ ...rule, params });
  };

  if (rule.rawMode || !ruleType) {
    return (
      <JsonField
        id={`${idPrefix}-raw`}
        label="Paramètres (JSON)"
        value={rule.rawParams}
        onChange={(v) => onChange({ ...rule, rawParams: v })}
        expect="object"
        rows={5}
        error={error}
        hint={ruleType ? undefined : "Type de règle inconnu du catalogue : paramètres en JSON."}
      />
    );
  }
  if (props.length === 0) {
    return <p className="text-xs text-muted-foreground">Cette règle n&apos;a pas de paramètre.</p>;
  }

  return (
    <div className="grid gap-3 md:grid-cols-2">
      {props.map(([key, schema]) => {
        const id = `${idPrefix}-p-${key}`;
        const isRequired = required.includes(key);
        const value = rule.params[key];
        const type = Array.isArray(schema.type) ? schema.type[0] : schema.type;
        const label = (
          <span className="font-mono text-[12px]">
            {key}
          </span>
        );
        const hint = schema.description;
        if (schema.enum && (type === "string" || !type)) {
          return (
            <Field key={key} id={id} label={label} hint={hint} required={isRequired}>
              <SimpleSelect
                id={id}
                value={typeof value === "string" ? value : DEFAULT}
                onValueChange={(v) => setParam(key, v === DEFAULT ? undefined : v)}
                options={[
                  { value: DEFAULT, label: schema.default !== undefined ? `Défaut (${String(schema.default)})` : "Non défini" },
                  ...schema.enum.map((e) => ({ value: String(e), label: enumLabel(String(e)) })),
                ]}
              />
            </Field>
          );
        }
        if (type === "boolean") {
          return (
            <div key={key} className="grid content-start gap-1.5">
              <Label htmlFor={id}>{label}</Label>
              <label className="flex h-9 items-center gap-2 text-[13px]">
                <Switch id={id} checked={value === undefined ? schema.default === true : value === true} onCheckedChange={(c) => setParam(key, c)} />
                {hint}
              </label>
            </div>
          );
        }
        if (type === "integer" || type === "number") {
          return (
            <Field key={key} id={id} label={label} hint={hint} required={isRequired}>
              <Input
                id={id}
                type="number"
                inputMode={type === "integer" ? "numeric" : "decimal"}
                step={type === "integer" ? 1 : "any"}
                min={schema.minimum}
                value={typeof value === "number" ? String(value) : ""}
                placeholder={schema.default !== undefined ? String(schema.default) : undefined}
                onChange={(e) => {
                  const t = e.target.value;
                  setParam(key, t === "" ? undefined : type === "integer" ? Math.trunc(Number(t)) : Number(t));
                }}
              />
            </Field>
          );
        }
        if (type === "array" && schema.items?.enum) {
          const selected = Array.isArray(value) ? value.map(String) : [];
          return (
            <fieldset key={key} className="grid gap-1.5 md:col-span-2">
              <legend className="mb-1 text-[13px] font-medium">
                {label}
                {hint ? <span className="ml-2 text-xs font-normal text-muted-foreground">{hint}</span> : null}
              </legend>
              <div className="flex flex-wrap gap-x-4 gap-y-2">
                {schema.items.enum.map((e) => {
                  const v = String(e);
                  const cid = `${id}-${v}`;
                  return (
                    <label key={v} htmlFor={cid} className="flex items-center gap-2 text-[13px]">
                      <Checkbox
                        id={cid}
                        checked={selected.includes(v)}
                        onCheckedChange={(c) => setParam(key, c ? [...selected, v] : selected.filter((x) => x !== v))}
                      />
                      {enumLabel(v)}
                    </label>
                  );
                })}
              </div>
            </fieldset>
          );
        }
        if (type === "array" && (!schema.items?.type || schema.items.type === "string")) {
          return (
            <Field key={key} id={id} label={label} hint={hint ?? "Entrée pour ajouter."} required={isRequired} className="md:col-span-2">
              <TagInput id={id} value={Array.isArray(value) ? value.map(String) : []} onChange={(v) => setParam(key, v)} max={200} />
            </Field>
          );
        }
        if (type === "string") {
          return (
            <Field key={key} id={id} label={label} hint={hint} required={isRequired}>
              <Input id={id} value={typeof value === "string" ? value : ""} onChange={(e) => setParam(key, e.target.value)} className="font-mono" />
            </Field>
          );
        }
        // object, untyped value (expected_value.value) or complex arrays: JSON editor.
        const draft = rule.paramDrafts[key] ?? (value === undefined ? "" : toJsonText(value));
        return (
          <JsonField
            key={key}
            id={id}
            label={label}
            hint={hint}
            value={draft}
            onChange={(t) => onChange({ ...rule, paramDrafts: { ...rule.paramDrafts, [key]: t } })}
            rows={4}
            className="md:col-span-2"
          />
        );
      })}
      {error ? (
        <p role="alert" className="text-xs font-medium text-destructive md:col-span-2">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export interface RuleBuilderProps {
  rules: RuleRow[];
  onChange: (rules: RuleRow[]) => void;
  meta: Meta | undefined;
  errors: ReadonlyArray<ApiFieldError>;
  /** Hidden rules are a maintainer feature. */
  canHide: boolean;
}

/** Ordered list of deterministic rules with a catalog-driven params form. */
export function RuleBuilder({ rules, onChange, meta, errors, canHide }: RuleBuilderProps) {
  const catalog = meta?.rule_types ?? [];
  const [newType, setNewType] = React.useState<string>("");
  const update = (i: number, rule: RuleRow) => onChange(rules.map((r, j) => (j === i ? rule : r)));
  const move = (i: number, delta: number) => {
    const next = [...rules];
    const [item] = next.splice(i, 1);
    if (item) next.splice(i + delta, 0, item);
    onChange(next);
  };

  const add = () => {
    const rt = catalog.find((t) => t.type === newType);
    if (!rt) return;
    const used = new Set(rules.map((r) => r.id));
    let n = rules.length;
    while (used.has(`R${n + 1}`)) n++;
    onChange([...rules, newRule(rt.type, rt.example ?? {}, n)]);
  };

  const criteriaOptions = [
    { value: DEFAULT, label: "Critère par défaut du type" },
    ...(meta?.criteria ?? []).map((c) => ({ value: c.key, label: c.name, description: c.key })),
  ];
  const errorTypeOptions = [
    { value: DEFAULT, label: "Type par défaut" },
    ...(meta?.error_types ?? []).map((e) => ({ value: e.code, label: e.label, description: e.code })),
  ];

  return (
    <div className="grid gap-3">
      {rules.length === 0 ? <p className="text-[13px] text-subtle-foreground">Aucune règle : ajoutez-en depuis le catalogue ci-dessous.</p> : null}
      {rules.map((rule, i) => {
        const rt = catalog.find((t) => t.type === rule.type);
        const prefix = `rules[${i}]`;
        const ruleErrors = errorsUnder(errors, prefix);
        const idp = `rule-${rule.uid}`;
        return (
          <div
            key={rule.uid}
            className={cn("grid gap-3 rounded-lg border bg-card p-3.5", ruleErrors.length ? "border-destructive/60" : "border-border")}
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="neutral" mono>
                #{i + 1}
              </Badge>
              <span className="text-[13px] font-semibold">{rt?.label ?? rule.type}</span>
              {rule.hidden ? (
                <Badge tone="violet" icon={<EyeOff aria-hidden />}>
                  Masquée
                </Badge>
              ) : null}
              <div className="ml-auto flex items-center gap-0.5">
                <Button
                  type="button"
                  variant="ghost"
                  size="xs"
                  leftIcon={<Braces aria-hidden />}
                  onClick={() => {
                    if (rule.rawMode) {
                      const parsed = parseJsonText(rule.rawParams, {});
                      if (!parsed.ok) return;
                      update(i, { ...rule, rawMode: false, params: (parsed.value ?? {}) as Record<string, unknown>, paramDrafts: {} });
                    } else {
                      const params = { ...rule.params };
                      for (const [k, t] of Object.entries(rule.paramDrafts)) {
                        const p = parseJsonText(t);
                        if (p.ok && p.value !== undefined) params[k] = p.value;
                      }
                      update(i, { ...rule, rawMode: true, rawParams: toJsonText(params), paramDrafts: {} });
                    }
                  }}
                  aria-pressed={rule.rawMode}
                >
                  {rule.rawMode ? "Formulaire" : "JSON"}
                </Button>
                <Button type="button" variant="ghost" size="icon-xs" onClick={() => move(i, -1)} disabled={i === 0} aria-label="Monter la règle">
                  <ArrowUp aria-hidden />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => move(i, 1)}
                  disabled={i === rules.length - 1}
                  aria-label="Descendre la règle"
                >
                  <ArrowDown aria-hidden />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => onChange(rules.filter((_, j) => j !== i))}
                  aria-label={`Supprimer la règle ${rule.id}`}
                  className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                >
                  <Trash2 aria-hidden />
                </Button>
              </div>
            </div>
            {rt?.description ? <p className="-mt-1 text-xs text-muted-foreground">{rt.description}</p> : null}

            <div className="grid gap-3 md:grid-cols-[8rem_minmax(0,1fr)]">
              <Field id={`${idp}-id`} label="Identifiant" error={fieldError(errors, `${prefix}.id`)}>
                <Input id={`${idp}-id`} value={rule.id} onChange={(e) => update(i, { ...rule, id: e.target.value })} className="font-mono" size="sm" />
              </Field>
              <Field id={`${idp}-type`} label="Type" error={fieldError(errors, `${prefix}.type`)}>
                <SimpleSelect
                  id={`${idp}-type`}
                  size="sm"
                  value={rule.type}
                  onValueChange={(v) => {
                    const t = catalog.find((x) => x.type === v);
                    update(i, { ...rule, type: v, params: { ...(t?.example ?? {}) }, paramDrafts: {}, rawParams: toJsonText(t?.example ?? {}) });
                  }}
                  options={[
                    ...catalog.map((t) => ({ value: t.type, label: t.label, description: t.type })),
                    ...(rt || !rule.type ? [] : [{ value: rule.type, label: rule.type, description: "Type inconnu" }]),
                  ]}
                />
              </Field>
            </div>

            <ParamsForm
              rule={rule}
              ruleType={rt}
              onChange={(r) => update(i, r)}
              idPrefix={idp}
              error={fieldError(errors, `${prefix}.params`, { deep: true })}
            />

            <details className="group text-[13px]" open={Boolean(rule.criterion_key || rule.error_type || rule.weight || rule.description || rule.severity !== "medium")}>
              <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                Évaluation : critère, gravité, type d&apos;erreur, poids
              </summary>
              <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <Field id={`${idp}-criterion`} label="Critère" hint={rt ? `Défaut : ${rt.default_criterion}` : undefined} error={fieldError(errors, `${prefix}.criterion_key`)}>
                  <SimpleSelect
                    id={`${idp}-criterion`}
                    size="sm"
                    value={rule.criterion_key || DEFAULT}
                    onValueChange={(v) => update(i, { ...rule, criterion_key: v === DEFAULT ? "" : v })}
                    options={criteriaOptions}
                  />
                </Field>
                <Field id={`${idp}-severity`} label="Gravité en cas d'échec" error={fieldError(errors, `${prefix}.severity`)}>
                  <SimpleSelect<ErrorSeverity>
                    id={`${idp}-severity`}
                    size="sm"
                    value={rule.severity}
                    onValueChange={(v) => update(i, { ...rule, severity: v })}
                    options={ERROR_SEVERITIES.map((s) => ({ value: s, label: getMeta(ERROR_SEVERITY_META, s).label }))}
                  />
                </Field>
                <Field
                  id={`${idp}-error-type`}
                  label="Type d'erreur"
                  hint={rt?.default_error_type ? `Défaut : ${rt.default_error_type}` : undefined}
                  error={fieldError(errors, `${prefix}.error_type`)}
                >
                  <SimpleSelect
                    id={`${idp}-error-type`}
                    size="sm"
                    value={rule.error_type || DEFAULT}
                    onValueChange={(v) => update(i, { ...rule, error_type: v === DEFAULT ? "" : v })}
                    options={errorTypeOptions}
                  />
                </Field>
                <Field id={`${idp}-weight`} label="Poids" hint="Défaut : 1" error={fieldError(errors, `${prefix}.weight`)}>
                  <Input id={`${idp}-weight`} size="sm" inputMode="decimal" value={rule.weight} onChange={(e) => update(i, { ...rule, weight: e.target.value })} />
                </Field>
                <Field id={`${idp}-description`} label="Description" className="md:col-span-2 xl:col-span-3" error={fieldError(errors, `${prefix}.description`)}>
                  <Input id={`${idp}-description`} size="sm" value={rule.description} onChange={(e) => update(i, { ...rule, description: e.target.value })} />
                </Field>
                <div className="grid content-end pb-1.5">
                  <label className={cn("flex items-center gap-2 text-[13px]", !canHide && "opacity-60")} title={canHide ? undefined : "Réservé aux mainteneurs."}>
                    <Switch checked={rule.hidden} onCheckedChange={(c) => update(i, { ...rule, hidden: c })} disabled={!canHide} aria-label="Règle masquée" />
                    Masquée aux non-mainteneurs
                  </label>
                </div>
              </div>
            </details>
            {ruleErrors.length && !fieldError(errors, `${prefix}.params`, { deep: true }) ? (
              <Alert tone="red" className="py-2">
                {ruleErrors.map((e) => e.message).join(" · ")}
              </Alert>
            ) : null}
          </div>
        );
      })}

      <div className="flex flex-col gap-2 rounded-lg border border-dashed border-border-strong p-3 sm:flex-row sm:items-center">
        <SimpleSelect
          aria-label="Type de règle à ajouter"
          size="sm"
          value={newType || undefined}
          onValueChange={setNewType}
          placeholder="Choisir un type de règle…"
          options={catalog.map((t) => ({ value: t.type, label: t.label, description: t.description }))}
          className="sm:max-w-md"
          contentClassName="max-w-[28rem]"
        />
        <Button type="button" variant="secondary" size="sm" leftIcon={<Plus aria-hidden />} onClick={add} disabled={!newType}>
          Ajouter la règle
        </Button>
      </div>
    </div>
  );
}
