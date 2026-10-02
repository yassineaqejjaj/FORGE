/**
 * Form model of the "new agent version" editor: conversion between the API payloads
 * (`AgentVersionOut` → form state → `AgentVersionCreateIn`) and override detection when the new
 * version is based on an existing one. No business rule here: validation is done by the API.
 */
import type { AgentVersion, AgentVersionCreateInput } from "@/lib/api/agents";
import { ADAPTER_KINDS, CONTEXT_SOURCES, isEnumValue, type AdapterKind, type ContextSource } from "@/lib/enums";

import { parseJsonText, toJsonText } from "./kit/json-field";

export interface ModelFormState {
  name: string;
  provider: string;
  model: string;
  model_version: string;
  temperature: string;
  top_p: string;
  max_tokens: string;
  seed: string;
  input_cost_per_mtok: string;
  output_cost_per_mtok: string;
  params: string;
}

export interface OrbitFormState {
  project: string;
  snapshot: string;
  version: string;
  base_url: string;
  merge: boolean;
  optional: boolean;
  timeout_seconds: string;
  /** Other keys of `context_config.orbit` (kept as is). */
  rest: Record<string, unknown>;
}

export interface VersionFormState {
  version: string;
  changelog: string;
  adapter_kind: AdapterKind;
  endpoint: string;
  useModel: boolean;
  model: ModelFormState;
  system_prompt: string;
  prompt_name: string;
  tools: string;
  tools_name: string;
  context_source: ContextSource;
  orbit: OrbitFormState;
  /** Other keys of `context_config` (kept as is). */
  context_rest: Record<string, unknown>;
  memory_config: string;
  orchestration_config: string;
  adapter_config: string;
  credential_id: string;
  budget: { max_tokens: string; max_cost: string; max_steps: string; timeout_seconds: string };
  max_concurrency: string;
  metadata: string;
}

const str = (v: unknown): string => (v === null || v === undefined ? "" : String(v));

export const EMPTY_MODEL: ModelFormState = {
  name: "",
  provider: "",
  model: "",
  model_version: "",
  temperature: "",
  top_p: "",
  max_tokens: "",
  seed: "",
  input_cost_per_mtok: "",
  output_cost_per_mtok: "",
  params: "",
};

export function emptyFormState(): VersionFormState {
  return {
    version: "",
    changelog: "",
    adapter_kind: "custom_api",
    endpoint: "",
    useModel: false,
    model: { ...EMPTY_MODEL },
    system_prompt: "",
    prompt_name: "",
    tools: "",
    tools_name: "",
    context_source: "scenario",
    orbit: { project: "", snapshot: "", version: "", base_url: "", merge: true, optional: false, timeout_seconds: "", rest: {} },
    context_rest: {},
    memory_config: "",
    orchestration_config: "",
    adapter_config: "",
    credential_id: "",
    budget: { max_tokens: "", max_cost: "", max_steps: "8", timeout_seconds: "" },
    max_concurrency: "",
    metadata: "",
  };
}

/** Form state prefilled from an existing version (label and changelog left blank). */
export function formStateFromVersion(v: AgentVersion): VersionFormState {
  const ctx = { ...(v.context_config ?? {}) } as Record<string, unknown>;
  const source = isEnumValue(CONTEXT_SOURCES, ctx.source) ? ctx.source : "scenario";
  const orbitRaw = ctx.orbit && typeof ctx.orbit === "object" ? { ...(ctx.orbit as Record<string, unknown>) } : {};
  delete ctx.source;
  delete ctx.orbit;
  const { project, snapshot, version, base_url, merge, optional, timeout_seconds, ...orbitRest } = orbitRaw;
  const m = v.model_configuration;
  const b = v.budget ?? {};
  return {
    version: "",
    changelog: "",
    adapter_kind: isEnumValue(ADAPTER_KINDS, v.adapter_kind) ? v.adapter_kind : "custom_api",
    endpoint: str(v.endpoint),
    useModel: Boolean(m),
    model: m
      ? {
          // Not prefilled: a changed model gets the default "<provider>/<model>" name from the API.
          name: "",
          provider: str(m.provider),
          model: str(m.model),
          model_version: str(m.model_version),
          temperature: str(m.temperature),
          top_p: str(m.top_p),
          max_tokens: str(m.max_tokens),
          seed: str(m.seed),
          input_cost_per_mtok: str(m.input_cost_per_mtok),
          output_cost_per_mtok: str(m.output_cost_per_mtok),
          params: toJsonText(m.params, true),
        }
      : { ...EMPTY_MODEL },
    system_prompt: v.system_prompt ?? "",
    prompt_name: v.prompt?.name ?? "",
    tools: v.tools.length ? toJsonText(v.tools) : "",
    tools_name: v.tool_configuration?.name ?? "",
    context_source: source,
    orbit: {
      project: str(project),
      snapshot: str(snapshot),
      version: str(version),
      base_url: str(base_url),
      merge: merge === undefined ? true : Boolean(merge),
      optional: Boolean(optional),
      timeout_seconds: str(timeout_seconds),
      rest: orbitRest,
    },
    context_rest: ctx,
    memory_config: toJsonText(v.memory_config, true),
    orchestration_config: toJsonText(v.orchestration_config, true),
    adapter_config: toJsonText(v.adapter_config, true),
    credential_id: v.credential?.id ?? "",
    budget: {
      max_tokens: str(b.max_tokens),
      max_cost: str(b.max_cost),
      max_steps: str(b.max_steps ?? 8),
      timeout_seconds: str(b.timeout_seconds),
    },
    max_concurrency: str(v.max_concurrency),
    metadata: toJsonText(v.metadata, true),
  };
}

function numberOrNull(text: string): number | null {
  const t = text.trim().replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function jsonObject(text: string): Record<string, unknown> {
  const r = parseJsonText(text, {});
  return r.ok && r.value && typeof r.value === "object" && !Array.isArray(r.value) ? (r.value as Record<string, unknown>) : {};
}

/** JSON editors of the form that currently hold invalid JSON (blocks submission). */
export function invalidJsonFields(s: VersionFormState): string[] {
  const out: string[] = [];
  const check = (label: string, text: string, kind: "object" | "array") => {
    const r = parseJsonText(text);
    if (!r.ok) out.push(label);
    else if (r.value !== undefined && (kind === "array" ? !Array.isArray(r.value) : typeof r.value !== "object" || Array.isArray(r.value)))
      out.push(label);
  };
  check("Outils", s.tools, "array");
  check("Mémoire", s.memory_config, "object");
  check("Orchestration", s.orchestration_config, "object");
  check("Configuration de l'adapter", s.adapter_config, "object");
  check("Métadonnées", s.metadata, "object");
  if (s.useModel) check("Paramètres du modèle", s.model.params, "object");
  return out;
}

type Payload = Omit<AgentVersionCreateInput, "changelog"> & { changelog?: string };

/** Behaviour fields of the payload built from a form state (label / changelog excluded). */
function behaviourPayload(s: VersionFormState): Payload {
  const p: Payload = {};
  p.adapter_kind = s.adapter_kind;
  p.endpoint = s.endpoint.trim() || null;
  p.model = s.useModel
    ? {
        name: s.model.name.trim() || null,
        provider: s.model.provider.trim(),
        model: s.model.model.trim(),
        model_version: s.model.model_version.trim() || null,
        temperature: numberOrNull(s.model.temperature),
        top_p: numberOrNull(s.model.top_p),
        max_tokens: numberOrNull(s.model.max_tokens),
        seed: numberOrNull(s.model.seed),
        params: jsonObject(s.model.params),
        input_cost_per_mtok: numberOrNull(s.model.input_cost_per_mtok),
        output_cost_per_mtok: numberOrNull(s.model.output_cost_per_mtok),
      }
    : null;
  p.system_prompt = s.system_prompt;
  const tools = parseJsonText(s.tools, []);
  p.tools = tools.ok && Array.isArray(tools.value) ? (tools.value as Payload["tools"]) : [];
  const context: Record<string, unknown> = { ...s.context_rest };
  if (s.context_source !== "scenario" || Object.keys(context).length) context.source = s.context_source;
  if (s.context_source === "orbit_snapshot" || s.context_source === "orbit_live") {
    const orbit: Record<string, unknown> = { ...s.orbit.rest, project: s.orbit.project.trim() };
    if (s.context_source === "orbit_snapshot" && s.orbit.snapshot.trim()) orbit.snapshot = s.orbit.snapshot.trim();
    if (s.orbit.version.trim()) orbit.version = s.orbit.version.trim();
    if (s.orbit.base_url.trim()) orbit.base_url = s.orbit.base_url.trim();
    if (!s.orbit.merge) orbit.merge = false;
    if (s.orbit.optional) orbit.optional = true;
    const timeout = numberOrNull(s.orbit.timeout_seconds);
    if (timeout !== null) orbit.timeout_seconds = timeout;
    context.orbit = orbit;
  }
  p.context_config = context;
  p.memory_config = jsonObject(s.memory_config);
  p.orchestration_config = jsonObject(s.orchestration_config);
  p.adapter_config = jsonObject(s.adapter_config);
  p.credential_id = s.credential_id || null;
  const budget: NonNullable<Payload["budget"]> = { max_steps: numberOrNull(s.budget.max_steps) ?? 8 } as NonNullable<Payload["budget"]>;
  const maxTokens = numberOrNull(s.budget.max_tokens);
  const maxCost = numberOrNull(s.budget.max_cost);
  const timeout = numberOrNull(s.budget.timeout_seconds);
  if (maxTokens !== null) budget.max_tokens = maxTokens;
  if (maxCost !== null) budget.max_cost = maxCost;
  if (timeout !== null) budget.timeout_seconds = timeout;
  p.budget = budget;
  p.max_concurrency = numberOrNull(s.max_concurrency);
  p.metadata = jsonObject(s.metadata);
  return p;
}

function stable(value: unknown): string {
  return JSON.stringify(value, (_k, v: unknown) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)))
      : v,
  );
}

/** Payload keys whose value differs from the base form state (empty array from scratch = every key). */
export function changedKeys(state: VersionFormState, base: VersionFormState | null): string[] {
  const current = behaviourPayload(state) as Record<string, unknown>;
  if (!base) return Object.keys(current);
  const reference = behaviourPayload(base) as Record<string, unknown>;
  return Object.keys(current).filter((k) => stable(current[k]) !== stable(reference[k]));
}

/**
 * `POST /agents/{id}/versions` body. From scratch: every field. Based on a version: only the
 * overrides (`base_version_id` + changed fields), so the API keeps everything else as is.
 */
export function buildVersionPayload(state: VersionFormState, base: { id: string; state: VersionFormState } | null): AgentVersionCreateInput {
  const full = behaviourPayload(state) as Record<string, unknown>;
  const keys = changedKeys(state, base?.state ?? null);
  const body: Record<string, unknown> = { changelog: state.changelog.trim() };
  if (state.version.trim()) body.version = state.version.trim();
  if (base) body.base_version_id = base.id;
  for (const k of keys) body[k] = full[k];
  if ("system_prompt" in body && state.prompt_name.trim()) body.prompt_name = state.prompt_name.trim();
  if ("tools" in body && state.tools_name.trim() && Array.isArray(body.tools) && body.tools.length) body.tools_name = state.tools_name.trim();
  return body as unknown as AgentVersionCreateInput;
}

/** Display-only suggestion of the next label ("1.3" → "1.4"); the API assigns it when left empty. */
export function suggestNextLabel(previous: string | null | undefined): string {
  if (!previous) return "1.0";
  const m = /^v?(\d+)(?:\.(\d+))?/.exec(previous.trim());
  if (!m) return `${previous}.1`;
  return `${Number(m[1])}.${Number(m[2] ?? 0) + 1}`;
}

/** Read / write one top-level key of a JSON object held as text (quick adapter fields). */
export function getJsonKey(text: string, key: string): string {
  const obj = jsonObject(text);
  return str(obj[key]);
}

export function setJsonKey(text: string, key: string, value: string): string {
  const r = parseJsonText(text, {});
  if (!r.ok) return text;
  const obj = r.value && typeof r.value === "object" && !Array.isArray(r.value) ? { ...(r.value as Record<string, unknown>) } : {};
  if (value === "") delete obj[key];
  else obj[key] = value;
  return Object.keys(obj).length ? toJsonText(obj) : "";
}
