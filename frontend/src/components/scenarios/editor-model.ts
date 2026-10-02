/**
 * Form model of the scenario editor (structured form ⇄ `ScenarioContentIn`). Pure conversions only:
 * every validation rule (rule params, criteria keys, input shape…) is enforced by the API, whose
 * field errors (`rules[1].params`, `criteria[0].key`…) are displayed next to the matching item.
 */
import { parseJsonText, toJsonText } from "@/components/agents/kit/json-field";
import type { ScenarioContentInput, ScenarioVersion } from "@/lib/api/scenarios";
import { DIFFICULTIES, ERROR_SEVERITIES, isEnumValue, type Difficulty, type ErrorSeverity } from "@/lib/enums";

let uidCounter = 0;
export const uid = () => `row-${Date.now().toString(36)}-${(uidCounter++).toString(36)}`;

export interface MessageRow {
  uid: string;
  role: string;
  content: string;
}

export interface DocumentRow {
  uid: string;
  id: string;
  title: string;
  content: string;
  source: string;
  extra: Record<string, unknown>;
}

export interface CriterionRow {
  uid: string;
  key: string;
  weight: string;
  question: string;
  rubric: string;
  extra: Record<string, unknown>;
}

export interface RuleRow {
  uid: string;
  id: string;
  type: string;
  params: Record<string, unknown>;
  /** Raw JSON drafts for params edited as JSON (objects, untyped values). */
  paramDrafts: Record<string, string>;
  /** Edit the whole params object as JSON. */
  rawMode: boolean;
  rawParams: string;
  description: string;
  criterion_key: string;
  severity: ErrorSeverity;
  error_type: string;
  weight: string;
  hidden: boolean;
  extra: Record<string, unknown>;
}

export interface MockRow {
  uid: string;
  tool: string;
  match: string;
  response: string;
  error: string;
  latency_ms: string;
}

export type EditMode = "form" | "json";

export interface ContentState {
  description: string;
  difficulty: Difficulty;
  inputMode: "prompt" | "messages" | "json";
  prompt: string;
  messages: MessageRow[];
  inputRest: Record<string, unknown>;
  inputJson: string;
  documents: DocumentRow[];
  contextRest: Record<string, unknown>;
  constraints: string[];
  expectedMode: "text" | "json";
  expectedText: string;
  expectedJson: string;
  expectedBehavior: string;
  criteriaMode: EditMode;
  criteria: CriterionRow[];
  criteriaJson: string;
  rulesMode: EditMode;
  rules: RuleRow[];
  rulesJson: string;
  mocksMode: EditMode;
  mocks: MockRow[];
  mocksJson: string;
}

const str = (v: unknown) => (v === null || v === undefined ? "" : typeof v === "string" ? v : JSON.stringify(v));
const rec = (v: unknown): Record<string, unknown> =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};

function omit(obj: Record<string, unknown>, keys: readonly string[]): Record<string, unknown> {
  return Object.fromEntries(Object.entries(obj).filter(([k]) => !keys.includes(k)));
}

export function emptyContent(): ContentState {
  return {
    description: "",
    difficulty: "medium",
    inputMode: "prompt",
    prompt: "",
    messages: [],
    inputRest: {},
    inputJson: "",
    documents: [],
    contextRest: {},
    constraints: [],
    expectedMode: "text",
    expectedText: "",
    expectedJson: "",
    expectedBehavior: "",
    criteriaMode: "form",
    criteria: [],
    criteriaJson: "",
    rulesMode: "form",
    rules: [],
    rulesJson: "",
    mocksMode: "form",
    mocks: [],
    mocksJson: "",
  };
}

export function newRule(type: string, example: Record<string, unknown> = {}, index = 0): RuleRow {
  return {
    uid: uid(),
    id: `R${index + 1}`,
    type,
    params: { ...example },
    paramDrafts: {},
    rawMode: false,
    rawParams: "",
    description: "",
    criterion_key: "",
    severity: "medium",
    error_type: "",
    weight: "",
    hidden: false,
    extra: {},
  };
}

export function ruleFromSpec(r: Record<string, unknown>, index: number): RuleRow {
  const params = rec(r.params);
  return {
    uid: uid(),
    id: str(r.id) || `R${index + 1}`,
    type: str(r.type),
    params,
    paramDrafts: {},
    rawMode: false,
    rawParams: toJsonText(params),
    description: str(r.description),
    criterion_key: str(r.criterion_key),
    severity: isEnumValue(ERROR_SEVERITIES, r.severity) ? r.severity : "medium",
    error_type: str(r.error_type),
    weight: r.weight === undefined || r.weight === null ? "" : String(r.weight),
    hidden: r.hidden === true,
    extra: omit(r, ["id", "type", "params", "description", "criterion_key", "severity", "error_type", "weight", "hidden"]),
  };
}

export function criterionFromSpec(c: Record<string, unknown> | string): CriterionRow {
  if (typeof c === "string") return { uid: uid(), key: c, weight: "", question: "", rubric: "", extra: {} };
  return {
    uid: uid(),
    key: str(c.key),
    weight: c.weight === undefined || c.weight === null ? "" : String(c.weight),
    question: str(c.question),
    rubric: str(c.rubric),
    extra: omit(c, ["key", "weight", "question", "rubric"]),
  };
}

export function mockFromSpec(m: Record<string, unknown>): MockRow {
  return {
    uid: uid(),
    tool: str(m.tool),
    match: m.match ? toJsonText(m.match) : "",
    response: m.response === undefined || m.response === null ? "" : toJsonText(m.response),
    error: str(m.error),
    latency_ms: m.latency_ms ? String(m.latency_ms) : "",
  };
}

/** Editor state prefilled from a (non-redacted) scenario version. */
export function contentFromVersion(v: ScenarioVersion): ContentState {
  const input = rec(v.input);
  const context = rec(v.context);
  const messages = Array.isArray(input.messages) ? (input.messages as Array<Record<string, unknown>>) : [];
  const docs = Array.isArray(context.documents) ? (context.documents as Array<Record<string, unknown>>) : [];
  const expected = v.expected_output;
  const expectedIsText = expected === null || expected === undefined || typeof expected === "string";
  const criteria = (v.criteria ?? []).map((c) => criterionFromSpec(c as Record<string, unknown>));
  const rules = (v.rules ?? []).map((r, i) => ruleFromSpec(r, i));
  const mocks = (v.tool_mocks ?? []).map((m) => mockFromSpec(m));
  return {
    description: v.description ?? "",
    difficulty: isEnumValue(DIFFICULTIES, v.difficulty) ? v.difficulty : "medium",
    inputMode: messages.length && typeof input.prompt !== "string" ? "messages" : "prompt",
    prompt: typeof input.prompt === "string" ? input.prompt : "",
    messages: messages.map((m) => ({ uid: uid(), role: str(m.role) || "user", content: str(m.content) })),
    inputRest: omit(input, ["prompt", "messages"]),
    inputJson: toJsonText(input, true),
    documents: docs.map((d) => ({
      uid: uid(),
      id: str(d.id),
      title: str(d.title),
      content: str(d.content),
      source: str(d.source),
      extra: omit(d, ["id", "title", "content", "source"]),
    })),
    contextRest: omit(context, ["documents"]),
    constraints: v.constraints ?? [],
    expectedMode: expectedIsText ? "text" : "json",
    expectedText: typeof expected === "string" ? expected : "",
    expectedJson: expectedIsText ? "" : toJsonText(expected),
    expectedBehavior: v.expected_behavior ?? "",
    criteriaMode: "form",
    criteria,
    criteriaJson: toJsonText(v.criteria ?? []),
    rulesMode: "form",
    rules,
    rulesJson: toJsonText(v.rules ?? []),
    mocksMode: "form",
    mocks,
    mocksJson: toJsonText(v.tool_mocks ?? []),
  };
}

function num(text: string): number | undefined {
  const t = text.trim().replace(",", ".");
  if (!t) return undefined;
  const n = Number(t);
  return Number.isFinite(n) ? n : undefined;
}

export function ruleToSpec(r: RuleRow): { spec: Record<string, unknown>; invalid: string[] } {
  const invalid: string[] = [];
  let params: Record<string, unknown> = { ...r.params };
  if (r.rawMode) {
    const parsed = parseJsonText(r.rawParams, {});
    if (!parsed.ok || typeof parsed.value !== "object" || Array.isArray(parsed.value)) invalid.push("params");
    else params = (parsed.value ?? {}) as Record<string, unknown>;
  } else {
    for (const [k, text] of Object.entries(r.paramDrafts)) {
      const parsed = parseJsonText(text);
      if (!parsed.ok) invalid.push(`params.${k}`);
      else if (parsed.value === undefined) delete params[k];
      else params[k] = parsed.value;
    }
  }
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "" || (Array.isArray(v) && v.length === 0)) delete params[k];
  }
  const spec: Record<string, unknown> = { ...r.extra, id: r.id.trim() || undefined, type: r.type, params };
  if (r.description.trim()) spec.description = r.description.trim();
  if (r.criterion_key) spec.criterion_key = r.criterion_key;
  spec.severity = r.severity;
  if (r.error_type) spec.error_type = r.error_type;
  const w = num(r.weight);
  if (w !== undefined) spec.weight = w;
  if (r.hidden) spec.hidden = true;
  if (spec.id === undefined) delete spec.id;
  return { spec, invalid };
}

export function criterionToSpec(c: CriterionRow): Record<string, unknown> {
  const spec: Record<string, unknown> = { ...c.extra, key: c.key.trim() };
  const w = num(c.weight);
  if (w !== undefined) spec.weight = w;
  if (c.question.trim()) spec.question = c.question.trim();
  if (c.rubric.trim()) spec.rubric = c.rubric.trim();
  return spec;
}

export function mockToSpec(m: MockRow): { spec: Record<string, unknown>; invalid: string[] } {
  const invalid: string[] = [];
  const spec: Record<string, unknown> = { tool: m.tool.trim() };
  const match = parseJsonText(m.match);
  if (!match.ok) invalid.push("match");
  else if (match.value !== undefined) spec.match = match.value;
  const response = parseJsonText(m.response);
  if (!response.ok) {
    // Plain text responses are accepted as strings.
    spec.response = m.response;
  } else if (response.value !== undefined) spec.response = response.value;
  if (m.error.trim()) spec.error = m.error.trim();
  const latency = num(m.latency_ms);
  if (latency !== undefined) spec.latency_ms = Math.round(latency);
  return { spec, invalid };
}

export interface BuildResult {
  content: ScenarioContentInput;
  /** Client-side JSON syntax problems, as field paths (blocks submission). */
  invalid: string[];
}

function parseArray(text: string, path: string, invalid: string[]): Array<Record<string, unknown>> {
  const parsed = parseJsonText(text, []);
  if (!parsed.ok || !Array.isArray(parsed.value)) {
    invalid.push(path);
    return [];
  }
  return parsed.value as Array<Record<string, unknown>>;
}

/** Complete `ScenarioContentIn` from the editor state. */
export function buildContent(s: ContentState): BuildResult {
  const invalid: string[] = [];
  let input: Record<string, unknown>;
  if (s.inputMode === "json") {
    const parsed = parseJsonText(s.inputJson, {});
    if (!parsed.ok || typeof parsed.value !== "object" || Array.isArray(parsed.value)) {
      invalid.push("input");
      input = {};
    } else input = (parsed.value ?? {}) as Record<string, unknown>;
  } else if (s.inputMode === "messages") {
    input = { ...s.inputRest, messages: s.messages.map((m) => ({ role: m.role, content: m.content })) };
  } else {
    input = { ...s.inputRest, prompt: s.prompt };
  }

  const context: Record<string, unknown> = { ...s.contextRest };
  if (s.documents.length) {
    context.documents = s.documents.map((d) => {
      const doc: Record<string, unknown> = { ...d.extra, id: d.id.trim(), title: d.title.trim(), content: d.content };
      if (d.source.trim()) doc.source = d.source.trim();
      return doc;
    });
  }

  let expected: unknown = null;
  if (s.expectedMode === "json") {
    const parsed = parseJsonText(s.expectedJson, null);
    if (!parsed.ok) invalid.push("expected_output");
    else expected = parsed.value;
  } else expected = s.expectedText.trim() ? s.expectedText : null;

  let criteria: Array<Record<string, unknown>>;
  if (s.criteriaMode === "json") criteria = parseArray(s.criteriaJson, "criteria", invalid);
  else criteria = s.criteria.filter((c) => c.key.trim()).map(criterionToSpec);

  let rules: Array<Record<string, unknown>>;
  if (s.rulesMode === "json") rules = parseArray(s.rulesJson, "rules", invalid);
  else
    rules = s.rules.map((r, i) => {
      const { spec, invalid: bad } = ruleToSpec(r);
      for (const b of bad) invalid.push(`rules[${i}].${b}`);
      return spec;
    });

  let mocks: Array<Record<string, unknown>>;
  if (s.mocksMode === "json") mocks = parseArray(s.mocksJson, "tool_mocks", invalid);
  else
    mocks = s.mocks.map((m, i) => {
      const { spec, invalid: bad } = mockToSpec(m);
      for (const b of bad) invalid.push(`tool_mocks[${i}].${b}`);
      return spec;
    });

  return {
    content: {
      description: s.description,
      difficulty: s.difficulty,
      input,
      context: Object.keys(context).length ? context : {},
      constraints: s.constraints,
      expected_output: expected,
      expected_behavior: s.expectedBehavior,
      criteria,
      rules,
      tool_mocks: mocks,
    },
    invalid,
  };
}

/** Switch a list section between the structured form and its JSON text; returns an error message on failure. */
export function toggleSectionMode(s: ContentState, section: "criteria" | "rules" | "mocks"): { next: ContentState } | { error: string } {
  if (section === "criteria") {
    if (s.criteriaMode === "form") {
      return { next: { ...s, criteriaMode: "json", criteriaJson: toJsonText(s.criteria.filter((c) => c.key.trim()).map(criterionToSpec)) } };
    }
    const parsed = parseJsonText(s.criteriaJson, []);
    if (!parsed.ok || !Array.isArray(parsed.value)) return { error: "Le JSON des critères doit être un tableau valide." };
    return { next: { ...s, criteriaMode: "form", criteria: (parsed.value as Array<Record<string, unknown> | string>).map(criterionFromSpec) } };
  }
  if (section === "rules") {
    if (s.rulesMode === "form") {
      const specs = s.rules.map((r) => ruleToSpec(r));
      if (specs.some((x) => x.invalid.length)) return { error: "Corrigez le JSON des paramètres de règles avant de basculer." };
      return { next: { ...s, rulesMode: "json", rulesJson: toJsonText(specs.map((x) => x.spec)) } };
    }
    const parsed = parseJsonText(s.rulesJson, []);
    if (!parsed.ok || !Array.isArray(parsed.value)) return { error: "Le JSON des règles doit être un tableau valide." };
    return { next: { ...s, rulesMode: "form", rules: (parsed.value as Array<Record<string, unknown>>).map((r, i) => ruleFromSpec(rec(r), i)) } };
  }
  if (s.mocksMode === "form") {
    const specs = s.mocks.map(mockToSpec);
    if (specs.some((x) => x.invalid.length)) return { error: "Corrigez le JSON des mocks avant de basculer." };
    return { next: { ...s, mocksMode: "json", mocksJson: toJsonText(specs.map((x) => x.spec)) } };
  }
  const parsed = parseJsonText(s.mocksJson, []);
  if (!parsed.ok || !Array.isArray(parsed.value)) return { error: "Le JSON des mocks doit être un tableau valide." };
  return { next: { ...s, mocksMode: "form", mocks: (parsed.value as Array<Record<string, unknown>>).map((m) => mockFromSpec(rec(m))) } };
}
