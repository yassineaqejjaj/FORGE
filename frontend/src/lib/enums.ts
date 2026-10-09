/**
 * FORGE enums — mirror of backend `forge/domain/enums.py` (docs/ARCHITECTURE.md §4).
 * Values MUST stay identical to the backend. Each enum exposes:
 *   - a `const` array of values (ordered for display) and its string-union type,
 *   - a `*_META` record with the French label, a colour tone and (when relevant) an icon name.
 * Pure data: no React import (icons are resolved by `components/domain/enum-icon.tsx`).
 * Labels are presentation only — every decision (verdicts, gates, redaction…) is computed by the API.
 */

/* -------------------------------------------------------------------------- */
/* Shared meta types                                                          */
/* -------------------------------------------------------------------------- */

/** Semantic colour tones, rendered by <Badge tone=…>, <ScoreBar tone=…>, etc. */
export const TONES = [
  "neutral",
  "teal",
  "green",
  "amber",
  "red",
  "blue",
  "sky",
  "violet",
  "orange",
  "pink",
] as const;
export type Tone = (typeof TONES)[number];

/** Lucide icon names used by enum metadata (resolved in `components/domain/enum-icon.tsx`). */
export type IconName =
  | "Eye"
  | "ClipboardCheck"
  | "PencilLine"
  | "Wrench"
  | "Crown"
  | "Globe"
  | "Lock"
  | "Sparkles"
  | "Clock"
  | "Loader"
  | "Gauge"
  | "CircleCheck"
  | "CircleX"
  | "Ban"
  | "FilePen"
  | "ListOrdered"
  | "Sigma"
  | "TrendingUp"
  | "TrendingDown"
  | "Equal"
  | "CircleHelp"
  | "Rocket"
  | "TriangleAlert"
  | "OctagonX"
  | "Bot"
  | "Cpu"
  | "Network"
  | "Plug"
  | "FlaskConical"
  | "Target"
  | "GitCompareArrows"
  | "Layers"
  | "Scale"
  | "User"
  | "Ruler"
  | "Activity";

export interface EnumMeta {
  /** French UI label. */
  label: string;
  /** Colour tone token. */
  tone: Tone;
  /** Optional lucide icon name. */
  icon?: IconName;
  /** Optional longer French description (tooltips, help text). */
  description?: string;
}

/** Safe lookup for values that may be unknown to this frontend version. */
export function getMeta<K extends string>(meta: Record<K, EnumMeta>, value: string | null | undefined): EnumMeta {
  if (value && Object.prototype.hasOwnProperty.call(meta, value)) {
    return meta[value as K];
  }
  return { label: value ?? "—", tone: "neutral" };
}

/** Type guard helper for enum values coming from untyped sources (URL params…). */
export function isEnumValue<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === "string" && (values as readonly string[]).includes(value);
}

/** `{ value, label }` options for selects / segmented controls, in display order. */
export function enumOptions<T extends string>(values: readonly T[], meta: Record<T, EnumMeta>) {
  return values.map((value) => ({ value, label: meta[value].label }));
}

/* -------------------------------------------------------------------------- */
/* Identity & access                                                          */
/* -------------------------------------------------------------------------- */

/** Platform roles, ordered: viewer ⊂ evaluator ⊂ editor ⊂ maintainer ⊂ admin. */
export const ROLES = ["viewer", "evaluator", "editor", "maintainer", "admin"] as const;
export type Role = (typeof ROLES)[number];

export const ROLE_META: Record<Role, EnumMeta> = {
  viewer: {
    label: "Lecteur",
    tone: "neutral",
    icon: "Eye",
    description: "Lecture de tout, sauf le contenu masqué des scénarios privés.",
  },
  evaluator: {
    label: "Évaluateur",
    tone: "sky",
    icon: "ClipboardCheck",
    description: "Lecture + évaluations humaines.",
  },
  editor: {
    label: "Éditeur",
    tone: "blue",
    icon: "PencilLine",
    description: "+ agents, versions, scénarios publics / fresh, runs, benchmarks, expériences, datasets.",
  },
  maintainer: {
    label: "Mainteneur",
    tone: "orange",
    icon: "Wrench",
    description: "+ scénarios privés, juges, configurations de score, taxonomie, critères.",
  },
  admin: {
    label: "Administrateur",
    tone: "violet",
    icon: "Crown",
    description: "+ utilisateurs, clés d'API, identifiants fournisseurs.",
  },
};

/** Numeric rank for role comparison (same order as the backend `ROLE_RANK`). */
export const ROLE_RANK: Record<Role, number> = { viewer: 0, evaluator: 1, editor: 2, maintainer: 3, admin: 4 };

/** True when `role` is at least `min`. Unknown / missing roles never pass. */
export function hasMinRole(role: string | null | undefined, min: Role): boolean {
  if (!role || !isEnumValue(ROLES, role)) return false;
  return ROLE_RANK[role] >= ROLE_RANK[min];
}

export const ACTOR_TYPES = ["user", "api_key", "system"] as const;
export type ActorType = (typeof ACTOR_TYPES)[number];

export const ACTOR_TYPE_META: Record<ActorType, EnumMeta> = {
  user: { label: "Utilisateur", tone: "neutral", icon: "User" },
  api_key: { label: "Clé d'API", tone: "blue", icon: "Plug" },
  system: { label: "Système", tone: "violet", icon: "Cpu" },
};

/* -------------------------------------------------------------------------- */
/* Classification (C0–C3, same policy as ORBIT)                               */
/* -------------------------------------------------------------------------- */

export const CLASSIFICATIONS = [0, 1, 2, 3] as const;
export type Classification = (typeof CLASSIFICATIONS)[number];

/** First level that requires the warning banner (backend `RESTRICTED_CLASSIFICATION_MIN`). */
export const RESTRICTED_CLASSIFICATION_MIN = 2;

export interface ClassificationMeta extends EnumMeta {
  code: `C${Classification}`;
  /** True for levels that require the C2/C3 warning banner. */
  sensitive: boolean;
}

export const CLASSIFICATION_META: Record<Classification, ClassificationMeta> = {
  0: { code: "C0", label: "Public", tone: "neutral", sensitive: false, description: "Diffusable sans restriction" },
  1: { code: "C1", label: "Interne", tone: "blue", sensitive: false, description: "Réservé aux collaborateurs" },
  2: {
    code: "C2",
    label: "Confidentiel",
    tone: "amber",
    sensitive: true,
    description: "Diffusion restreinte aux personnes habilitées",
  },
  3: { code: "C3", label: "Secret", tone: "red", sensitive: true, description: "Accès strictement nominatif" },
};

/** Clamp any number to a valid classification level. */
export function toClassification(value: number | null | undefined): Classification {
  const n = Math.round(Number(value ?? 0));
  if (Number.isNaN(n) || n <= 0) return 0;
  if (n >= 3) return 3;
  return n as Classification;
}

export function classificationCode(value: number | null | undefined): `C${Classification}` {
  return CLASSIFICATION_META[toClassification(value)].code;
}

export function isSensitiveClassification(value: number | null | undefined): boolean {
  return toClassification(value) >= RESTRICTED_CLASSIFICATION_MIN;
}

/* -------------------------------------------------------------------------- */
/* Agents                                                                     */
/* -------------------------------------------------------------------------- */

export const ADAPTER_KINDS = ["openai", "anthropic", "nova", "custom_api", "mock"] as const;
export type AdapterKind = (typeof ADAPTER_KINDS)[number];

export const ADAPTER_KIND_META: Record<AdapterKind, EnumMeta> = {
  openai: {
    label: "OpenAI-compatible",
    tone: "teal",
    icon: "Cpu",
    description: "Chat completions OpenAI-compatibles (OpenAI, vLLM, Ollama, Mistral…).",
  },
  anthropic: { label: "Anthropic", tone: "orange", icon: "Cpu", description: "API Anthropic Messages." },
  nova: { label: "NOVA", tone: "red", icon: "Network", description: "Agents orchestrés NOVA (NOVA Agent Protocol)." },
  custom_api: {
    label: "API personnalisée",
    tone: "blue",
    icon: "Plug",
    description: "Tout agent HTTP (FORGE Agent Protocol ou requête / réponse mappées).",
  },
  mock: { label: "Simulé", tone: "neutral", icon: "FlaskConical", description: "Agent scripté déterministe (tests, démos)." },
};

export const PROVIDER_KINDS = ["openai", "anthropic", "nova", "orbit", "http"] as const;
export type ProviderKind = (typeof PROVIDER_KINDS)[number];

export const PROVIDER_KIND_META: Record<ProviderKind, EnumMeta> = {
  openai: { label: "OpenAI-compatible", tone: "teal" },
  anthropic: { label: "Anthropic", tone: "orange" },
  nova: { label: "NOVA", tone: "red" },
  orbit: { label: "ORBIT", tone: "teal" },
  http: { label: "HTTP générique", tone: "blue", description: "Secret bearer / en-tête pour une API personnalisée." },
};

export const CONTEXT_SOURCES = ["scenario", "orbit_snapshot", "orbit_live", "none"] as const;
export type ContextSource = (typeof CONTEXT_SOURCES)[number];

export const CONTEXT_SOURCE_META: Record<ContextSource, EnumMeta> = {
  scenario: { label: "Contexte du scénario", tone: "neutral", description: "Uniquement le contexte fourni par le scénario." },
  orbit_snapshot: {
    label: "Snapshot ORBIT",
    tone: "teal",
    description: "Snapshot ORBIT épinglé (reproductible).",
  },
  orbit_live: {
    label: "ORBIT en direct",
    tone: "sky",
    description: "Assemblage de contexte ORBIT en direct (identifiant de requête tracé).",
  },
  none: { label: "Aucun contexte", tone: "neutral" },
};

/* -------------------------------------------------------------------------- */
/* Scenarios                                                                  */
/* -------------------------------------------------------------------------- */

export const SCENARIO_VISIBILITIES = ["public", "private", "fresh"] as const;
export type ScenarioVisibility = (typeof SCENARIO_VISIBILITIES)[number];

export const SCENARIO_VISIBILITY_META: Record<ScenarioVisibility, EnumMeta> = {
  public: {
    label: "Public",
    tone: "blue",
    icon: "Globe",
    description: "Visible et utilisable pendant le développement.",
  },
  private: {
    label: "Privé",
    tone: "violet",
    icon: "Lock",
    description: "Contenu masqué : test de généralisation (résultats visibles, contenu réservé aux mainteneurs).",
  },
  fresh: {
    label: "Fresh",
    tone: "teal",
    icon: "Sparkles",
    description: "Créé récemment : détecte le sur-apprentissage du benchmark.",
  },
};

export const DIFFICULTIES = ["easy", "medium", "hard", "expert"] as const;
export type Difficulty = (typeof DIFFICULTIES)[number];

export const DIFFICULTY_META: Record<Difficulty, EnumMeta> = {
  easy: { label: "Facile", tone: "green" },
  medium: { label: "Intermédiaire", tone: "sky" },
  hard: { label: "Difficile", tone: "amber" },
  expert: { label: "Expert", tone: "red" },
};

/** Suggested scenario categories (free text is accepted: the list is extensible). */
export const SCENARIO_CATEGORIES: Record<string, string> = {
  product_management: "Product Management",
  discovery: "Discovery",
  delivery: "Delivery",
  compliance: "Conformité",
  customer_support: "Support client",
  analysis: "Analyse",
  document_research: "Recherche documentaire",
  multi_agent: "Multi-agent",
  multi_step: "Tâches multi-étapes",
};

export function scenarioCategoryLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return SCENARIO_CATEGORIES[value] ?? value;
}

export const DATASET_KINDS = ["context", "gold"] as const;
export type DatasetKind = (typeof DATASET_KINDS)[number];

export const DATASET_KIND_META: Record<DatasetKind, EnumMeta> = {
  context: { label: "Contexte", tone: "neutral", description: "Documents / enregistrements rattachés aux scénarios." },
  gold: { label: "Gold (calibration)", tone: "amber", description: "Runs sélectionnés pour la calibration humaine." },
};

/* -------------------------------------------------------------------------- */
/* Runs & traces                                                              */
/* -------------------------------------------------------------------------- */

export const RUN_STATUSES = ["pending", "running", "evaluating", "completed", "failed", "cancelled"] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

export const RUN_STATUS_META: Record<RunStatus, EnumMeta> = {
  pending: { label: "En attente", tone: "neutral", icon: "Clock" },
  running: { label: "Exécution", tone: "blue", icon: "Loader" },
  evaluating: { label: "Évaluation", tone: "violet", icon: "Gauge" },
  completed: { label: "Terminé", tone: "green", icon: "CircleCheck" },
  failed: { label: "Échec", tone: "red", icon: "CircleX" },
  cancelled: { label: "Annulé", tone: "neutral", icon: "Ban" },
};

export const TERMINAL_RUN_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>(["completed", "failed", "cancelled"]);
/** Statuses shown with a pulsing dot (work in progress). */
export const ACTIVE_RUN_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>(["running", "evaluating"]);

export const RUN_ORIGINS = ["adhoc", "benchmark", "experiment", "observed"] as const;
export type RunOrigin = (typeof RUN_ORIGINS)[number];

export const RUN_ORIGIN_META: Record<RunOrigin, EnumMeta> = {
  adhoc: { label: "Ponctuel", tone: "neutral", icon: "Target" },
  benchmark: { label: "Benchmark", tone: "blue", icon: "Layers" },
  experiment: { label: "Expérience", tone: "violet", icon: "GitCompareArrows" },
  observed: { label: "Observé", tone: "green", icon: "Eye" },
};

export const EXPERIMENT_ARMS = ["baseline", "candidate"] as const;
export type ExperimentArm = (typeof EXPERIMENT_ARMS)[number];

export const EXPERIMENT_ARM_META: Record<ExperimentArm, EnumMeta> = {
  baseline: { label: "Référence", tone: "neutral" },
  candidate: { label: "Candidate", tone: "orange" },
};

export const TRACE_EVENT_TYPES = [
  "run_started",
  "context_prepared",
  "reasoning",
  "message",
  "llm_call",
  "tool_call",
  "tool_result",
  "retrieval",
  "memory",
  "agent_handoff",
  "decision",
  "error",
  "final_answer",
  "run_completed",
  "custom",
] as const;
export type TraceEventType = (typeof TRACE_EVENT_TYPES)[number];

export const TRACE_EVENT_TYPE_META: Record<TraceEventType, EnumMeta> = {
  run_started: { label: "Début du run", tone: "neutral" },
  context_prepared: { label: "Contexte préparé", tone: "teal" },
  reasoning: { label: "Raisonnement", tone: "violet" },
  message: { label: "Message", tone: "neutral" },
  llm_call: { label: "Appel LLM", tone: "blue" },
  tool_call: { label: "Appel d'outil", tone: "orange" },
  tool_result: { label: "Résultat d'outil", tone: "amber" },
  retrieval: { label: "Recherche", tone: "sky" },
  memory: { label: "Mémoire", tone: "teal" },
  agent_handoff: { label: "Délégation d'agent", tone: "pink" },
  decision: { label: "Décision", tone: "violet" },
  error: { label: "Erreur", tone: "red" },
  final_answer: { label: "Réponse finale", tone: "green" },
  run_completed: { label: "Fin du run", tone: "neutral" },
  custom: { label: "Personnalisé", tone: "neutral" },
};

export const TRACE_EVENT_SOURCES = ["runner", "adapter", "otlp", "api"] as const;
export type TraceEventSource = (typeof TRACE_EVENT_SOURCES)[number];

export const TRACE_EVENT_SOURCE_META: Record<TraceEventSource, EnumMeta> = {
  runner: { label: "Runner FORGE", tone: "orange", description: "Enregistré par FORGE autour de l'appel à l'adapter." },
  adapter: { label: "Adapter", tone: "blue", description: "Rapporté par l'adapter (boucle d'outils, réponse)." },
  otlp: { label: "OpenTelemetry", tone: "violet", description: "Spans OTLP poussés par l'agent." },
  api: { label: "API d'événements", tone: "teal", description: "Événements JSON poussés sur /runs/{id}/events." },
};

export const EVENT_STATUSES = ["ok", "error"] as const;
export type EventStatus = (typeof EVENT_STATUSES)[number];

export const EVENT_STATUS_META: Record<EventStatus, EnumMeta> = {
  ok: { label: "OK", tone: "green" },
  error: { label: "Erreur", tone: "red" },
};

/* -------------------------------------------------------------------------- */
/* Evaluation                                                                 */
/* -------------------------------------------------------------------------- */

export const DIMENSIONS = [
  "quality",
  "coherence",
  "reasoning",
  "safety",
  "robustness",
  "cost",
  "latency",
  "ux",
] as const;
export type Dimension = (typeof DIMENSIONS)[number];

export interface DimensionMeta extends EnumMeta {
  /** Short label for charts (radar axes, compact legends). */
  short: string;
  /** Stable identity colour (CSS variable, theme-aware). */
  color: string;
}

/** Labels identical to backend `DIMENSION_LABELS`. */
export const DIMENSION_META: Record<Dimension, DimensionMeta> = {
  quality: {
    label: "Qualité",
    short: "Qualité",
    tone: "blue",
    color: "var(--dim-quality)",
    description: "Exactitude, complétude, utilité, format et sources.",
  },
  coherence: {
    label: "Cohérence",
    short: "Cohérence",
    tone: "teal",
    color: "var(--dim-coherence)",
    description: "Absence de contradiction, alignement avec la demande, respect des contraintes.",
  },
  reasoning: {
    label: "Raisonnement",
    short: "Raisonnement",
    tone: "violet",
    color: "var(--dim-reasoning)",
    description: "Justification, pertinence des choix, cohérence des étapes.",
  },
  safety: {
    label: "Sécurité",
    short: "Sécurité",
    tone: "green",
    color: "var(--dim-safety)",
    description: "Règles métier, données sensibles, comportements interdits.",
  },
  robustness: {
    label: "Robustesse",
    short: "Robustesse",
    tone: "orange",
    color: "var(--dim-robustness)",
    description: "Stabilité du score sur les variantes et répétitions (mesurée sur un groupe de runs).",
  },
  cost: {
    label: "Coût",
    short: "Coût",
    tone: "amber",
    color: "var(--dim-cost)",
    description: "Coût estimé et tokens rapportés aux cibles de la configuration.",
  },
  latency: {
    label: "Latence",
    short: "Latence",
    tone: "sky",
    color: "var(--dim-latency)",
    description: "Temps de bout en bout rapporté aux cibles de la configuration.",
  },
  ux: {
    label: "Expérience utilisateur",
    short: "UX",
    tone: "pink",
    color: "var(--dim-ux)",
    description: "Clarté, charge de correction, utilité perçue.",
  },
};

/** Dimensions computed on groups of runs (variants / repetitions), never on a single run. */
export const GROUP_DIMENSIONS: ReadonlySet<Dimension> = new Set<Dimension>(["robustness"]);

/** Dimension of a criterion key ("quality.accuracy" → "quality"), when it is a known dimension. */
export function criterionDimension(criterionKey: string | null | undefined): Dimension | null {
  const head = criterionKey?.split(".")[0];
  return isEnumValue(DIMENSIONS, head) ? head : null;
}

export const EVALUATOR_KINDS = ["rule", "metric", "llm_judge", "human", "aggregate"] as const;
export type EvaluatorKind = (typeof EVALUATOR_KINDS)[number];

export const EVALUATOR_KIND_META: Record<EvaluatorKind, EnumMeta> = {
  rule: { label: "Règle", tone: "blue", icon: "Ruler", description: "Règle déterministe." },
  metric: { label: "Métrique", tone: "sky", icon: "Activity", description: "Valeur mesurée normalisée (coût, latence, tokens)." },
  llm_judge: { label: "Juge LLM", tone: "violet", icon: "Bot", description: "Verdict d'un juge LLM." },
  human: { label: "Humain", tone: "green", icon: "User", description: "Évaluation humaine." },
  aggregate: { label: "Agrégat", tone: "orange", icon: "Sigma", description: "Agrégation multi-juges." },
};

export const SCORE_SOURCES = ["ai", "rule", "metric", "human"] as const;
export type ScoreSource = (typeof SCORE_SOURCES)[number];

export const SCORE_SOURCE_META: Record<ScoreSource, EnumMeta> = {
  ai: { label: "IA", tone: "violet", icon: "Bot" },
  rule: { label: "Règle", tone: "blue", icon: "Ruler" },
  metric: { label: "Métrique", tone: "sky", icon: "Activity" },
  human: { label: "Humain", tone: "green", icon: "User" },
};

export const RULE_TYPES = [
  "required_fields",
  "json_valid",
  "json_schema",
  "regex_match",
  "regex_absent",
  "contains",
  "not_contains",
  "sections_present",
  "citation_required",
  "source_present",
  "no_pii",
  "expected_value",
  "max_length",
  "min_length",
  "tool_called",
  "tool_not_called",
  "max_tool_calls",
  "max_latency",
  "max_cost",
  "no_canary",
] as const;
export type RuleType = (typeof RULE_TYPES)[number];

export const RULE_TYPE_META: Record<RuleType, EnumMeta> = {
  required_fields: { label: "Champs requis", tone: "blue", description: "Chemins JSON devant exister dans la sortie." },
  json_valid: { label: "JSON valide", tone: "blue" },
  json_schema: { label: "Schéma JSON", tone: "blue" },
  regex_match: { label: "Motif présent", tone: "teal" },
  regex_absent: { label: "Motif absent", tone: "red" },
  contains: { label: "Mots-clés présents", tone: "teal" },
  not_contains: { label: "Mots-clés interdits", tone: "red" },
  sections_present: { label: "Sections présentes", tone: "blue" },
  citation_required: { label: "Citations requises", tone: "sky" },
  source_present: { label: "Source citée", tone: "sky" },
  no_pii: { label: "Aucune donnée personnelle", tone: "green" },
  expected_value: { label: "Valeur attendue", tone: "teal" },
  max_length: { label: "Longueur maximale", tone: "neutral" },
  min_length: { label: "Longueur minimale", tone: "neutral" },
  tool_called: { label: "Outil appelé", tone: "orange" },
  tool_not_called: { label: "Outil non appelé", tone: "orange" },
  max_tool_calls: { label: "Appels d'outils maximum", tone: "orange" },
  max_latency: { label: "Latence maximale", tone: "sky" },
  max_cost: { label: "Coût maximal", tone: "amber" },
  no_canary: { label: "Aucun canari", tone: "violet", description: "La sortie ne contient aucun canari de scénario privé." },
};

export const JUDGE_PROVIDERS = ["openai", "anthropic", "heuristic"] as const;
export type JudgeProvider = (typeof JUDGE_PROVIDERS)[number];

export const JUDGE_PROVIDER_META: Record<JudgeProvider, EnumMeta> = {
  openai: { label: "OpenAI-compatible", tone: "teal", icon: "Bot" },
  anthropic: { label: "Anthropic", tone: "orange", icon: "Bot" },
  heuristic: {
    label: "Heuristique",
    tone: "neutral",
    icon: "Scale",
    description: "Juge déterministe hors ligne (tests, démo sans clé d'API) ; confiance plafonnée à 0,6.",
  },
};

export const AGGREGATION_METHODS = ["mean", "median", "majority_vote", "weighted", "min", "custom"] as const;
export type AggregationMethod = (typeof AGGREGATION_METHODS)[number];

export const AGGREGATION_METHOD_META: Record<AggregationMethod, EnumMeta> = {
  mean: { label: "Moyenne", tone: "neutral" },
  median: { label: "Médiane", tone: "neutral" },
  majority_vote: { label: "Vote majoritaire", tone: "neutral", description: "Note arrondie la plus fréquente (égalité → médiane)." },
  weighted: { label: "Moyenne pondérée", tone: "neutral", description: "Pondération par juge." },
  min: { label: "Minimum (le plus sévère)", tone: "neutral" },
  custom: { label: "Expression personnalisée", tone: "violet", description: "Expression sûre sur scores, poids et confiances." },
};

export const ERROR_SEVERITIES = ["low", "medium", "high", "critical"] as const;
export type ErrorSeverity = (typeof ERROR_SEVERITIES)[number];

export const ERROR_SEVERITY_META: Record<ErrorSeverity, EnumMeta> = {
  low: { label: "Faible", tone: "neutral" },
  medium: { label: "Moyenne", tone: "amber" },
  high: { label: "Haute", tone: "orange" },
  critical: { label: "Critique", tone: "red" },
};

export const SEVERITY_RANK: Record<ErrorSeverity, number> = { low: 0, medium: 1, high: 2, critical: 3 };

export const BUILTIN_ERROR_TYPES = [
  "HALLUCINATION",
  "CONTRADICTION",
  "MISSING_INFORMATION",
  "WRONG_TOOL",
  "TOOL_FAILURE",
  "POLICY_VIOLATION",
  "DATA_LEAK",
  "BAD_REASONING",
  "INSTRUCTION_FAILURE",
  "FORMAT_ERROR",
  "SOURCE_ERROR",
  "MEMORY_ERROR",
  "EXECUTION_ERROR",
  "TIMEOUT",
  "BUDGET_EXCEEDED",
  "CONTAMINATION",
] as const;
export type BuiltinErrorType = (typeof BUILTIN_ERROR_TYPES)[number];

export interface ErrorTypeMeta extends EnumMeta {
  /** Default severity (backend `forge.domain.taxonomy`). */
  defaultSeverity: ErrorSeverity;
  dimension: Dimension;
}

/**
 * Built-in taxonomy labels (mirror of `forge/domain/taxonomy.py`). The taxonomy is extensible:
 * custom codes come from `GET /error-types` and fall back to their raw code here.
 */
export const BUILTIN_ERROR_TYPE_META: Record<BuiltinErrorType, ErrorTypeMeta> = {
  HALLUCINATION: {
    label: "Hallucination",
    tone: "red",
    defaultSeverity: "high",
    dimension: "quality",
    description: "Affirmation non étayée par le contexte, les sources ou les faits connus.",
  },
  CONTRADICTION: {
    label: "Contradiction",
    tone: "orange",
    defaultSeverity: "high",
    dimension: "coherence",
    description: "La réponse se contredit ou contredit le contexte fourni.",
  },
  MISSING_INFORMATION: {
    label: "Information manquante",
    tone: "amber",
    defaultSeverity: "medium",
    dimension: "quality",
    description: "Un élément demandé ou attendu est absent de la réponse.",
  },
  WRONG_TOOL: {
    label: "Mauvais outil",
    tone: "violet",
    defaultSeverity: "medium",
    dimension: "reasoning",
    description: "L'agent a utilisé un outil inadapté, inutile ou avec de mauvais paramètres.",
  },
  TOOL_FAILURE: {
    label: "Échec d'outil",
    tone: "violet",
    defaultSeverity: "medium",
    dimension: "reasoning",
    description: "Un appel d'outil a échoué ou son résultat a été ignoré.",
  },
  POLICY_VIOLATION: {
    label: "Violation de règle",
    tone: "red",
    defaultSeverity: "high",
    dimension: "safety",
    description: "Une règle métier, de conformité ou de comportement a été enfreinte.",
  },
  DATA_LEAK: {
    label: "Fuite de données",
    tone: "red",
    defaultSeverity: "critical",
    dimension: "safety",
    description: "Des données personnelles ou confidentielles apparaissent dans la sortie.",
  },
  BAD_REASONING: {
    label: "Raisonnement défaillant",
    tone: "violet",
    defaultSeverity: "medium",
    dimension: "reasoning",
    description: "Étapes incohérentes, justification absente ou choix non motivés.",
  },
  INSTRUCTION_FAILURE: {
    label: "Consigne non respectée",
    tone: "amber",
    defaultSeverity: "medium",
    dimension: "coherence",
    description: "Une contrainte explicite du scénario n'a pas été respectée.",
  },
  FORMAT_ERROR: {
    label: "Erreur de format",
    tone: "sky",
    defaultSeverity: "low",
    dimension: "quality",
    description: "Format de sortie invalide (JSON, schéma, sections, longueur).",
  },
  SOURCE_ERROR: {
    label: "Erreur de source",
    tone: "orange",
    defaultSeverity: "high",
    dimension: "quality",
    description: "Source absente, inventée ou qui ne soutient pas l'affirmation citée.",
  },
  MEMORY_ERROR: {
    label: "Erreur de mémoire",
    tone: "teal",
    defaultSeverity: "medium",
    dimension: "coherence",
    description: "Utilisation d'une information obsolète, remplacée ou mal mémorisée.",
  },
  EXECUTION_ERROR: {
    label: "Erreur d'exécution",
    tone: "neutral",
    defaultSeverity: "high",
    dimension: "quality",
    description: "L'agent n'a pas pu être exécuté (erreur HTTP, réponse invalide…).",
  },
  TIMEOUT: {
    label: "Délai dépassé",
    tone: "neutral",
    defaultSeverity: "high",
    dimension: "latency",
    description: "L'exécution a dépassé le délai autorisé.",
  },
  BUDGET_EXCEEDED: {
    label: "Budget dépassé",
    tone: "amber",
    defaultSeverity: "medium",
    dimension: "cost",
    description: "L'exécution a dépassé le budget de tokens ou de coût.",
  },
  CONTAMINATION: {
    label: "Contamination du benchmark",
    tone: "red",
    defaultSeverity: "critical",
    dimension: "safety",
    description: "Contenu d'un scénario privé (canari, résultat attendu) détecté côté agent.",
  },
};

/** Operational error types (the run itself failed; never produced by judges). */
export const OPERATIONAL_ERROR_TYPES: ReadonlySet<BuiltinErrorType> = new Set<BuiltinErrorType>([
  "EXECUTION_ERROR",
  "TIMEOUT",
  "BUDGET_EXCEEDED",
]);

export const GATE_ACTIONS = ["fail", "cap"] as const;
export type GateAction = (typeof GATE_ACTIONS)[number];

export const GATE_ACTION_META: Record<GateAction, EnumMeta> = {
  fail: { label: "Invalider le run", tone: "red", description: "Composite forcé à 0 et run marqué en échec de garde-fou." },
  cap: { label: "Plafonner le score", tone: "amber", description: "Composite plafonné à la valeur indiquée (0–100)." },
};

export const RECOMMENDATION_CATEGORIES = [
  "system_prompt",
  "rule",
  "retrieval",
  "model",
  "context",
  "tools",
  "orchestration",
  "memory",
  "output_format",
] as const;
export type RecommendationCategory = (typeof RECOMMENDATION_CATEGORIES)[number];

export const RECOMMENDATION_CATEGORY_META: Record<RecommendationCategory, EnumMeta> = {
  system_prompt: { label: "Prompt système", tone: "violet" },
  rule: { label: "Règles", tone: "blue" },
  retrieval: { label: "Recherche documentaire", tone: "sky" },
  model: { label: "Modèle", tone: "orange" },
  context: { label: "Contexte", tone: "teal" },
  tools: { label: "Outils", tone: "amber" },
  orchestration: { label: "Orchestration", tone: "pink" },
  memory: { label: "Mémoire", tone: "teal" },
  output_format: { label: "Format de sortie", tone: "neutral" },
};

export const PRIORITIES = ["p0", "p1", "p2"] as const;
export type Priority = (typeof PRIORITIES)[number];

export const PRIORITY_META: Record<Priority, EnumMeta> = {
  p0: { label: "P0 · Critique", tone: "red" },
  p1: { label: "P1 · Importante", tone: "amber" },
  p2: { label: "P2 · Souhaitable", tone: "neutral" },
};

export const FEEDBACK_SCOPES = ["run", "benchmark", "experiment"] as const;
export type FeedbackScope = (typeof FEEDBACK_SCOPES)[number];

export const FEEDBACK_SCOPE_META: Record<FeedbackScope, EnumMeta> = {
  run: { label: "Run", tone: "neutral" },
  benchmark: { label: "Benchmark", tone: "blue" },
  experiment: { label: "Expérience", tone: "violet" },
};

/* -------------------------------------------------------------------------- */
/* Benchmarks & experiments                                                   */
/* -------------------------------------------------------------------------- */

export const EXECUTION_STATUSES = [
  "draft",
  "queued",
  "running",
  "aggregating",
  "completed",
  "failed",
  "cancelled",
] as const;
export type ExecutionStatus = (typeof EXECUTION_STATUSES)[number];

export const EXECUTION_STATUS_META: Record<ExecutionStatus, EnumMeta> = {
  draft: { label: "Brouillon", tone: "neutral", icon: "FilePen" },
  queued: { label: "En file", tone: "sky", icon: "ListOrdered" },
  running: { label: "En cours", tone: "blue", icon: "Loader" },
  aggregating: { label: "Agrégation", tone: "violet", icon: "Sigma" },
  completed: { label: "Terminée", tone: "green", icon: "CircleCheck" },
  failed: { label: "Échec", tone: "red", icon: "CircleX" },
  cancelled: { label: "Annulée", tone: "neutral", icon: "Ban" },
};

export const ACTIVE_EXECUTION_STATUSES: ReadonlySet<ExecutionStatus> = new Set<ExecutionStatus>([
  "queued",
  "running",
  "aggregating",
]);

export const VERDICTS = ["better", "worse", "equivalent", "inconclusive"] as const;
export type Verdict = (typeof VERDICTS)[number];

export const VERDICT_META: Record<Verdict, EnumMeta> = {
  better: { label: "Meilleure", tone: "green", icon: "TrendingUp" },
  worse: { label: "Moins bonne", tone: "red", icon: "TrendingDown" },
  equivalent: { label: "Équivalente", tone: "blue", icon: "Equal" },
  inconclusive: { label: "Non concluant", tone: "neutral", icon: "CircleHelp" },
};

export const REGRESSION_SEVERITIES = ["minor", "major", "critical"] as const;
export type RegressionSeverity = (typeof REGRESSION_SEVERITIES)[number];

export const REGRESSION_SEVERITY_META: Record<RegressionSeverity, EnumMeta> = {
  minor: { label: "Mineure", tone: "amber" },
  major: { label: "Majeure", tone: "orange" },
  critical: { label: "Critique", tone: "red" },
};

export const RECOMMENDATIONS = ["ship", "ship_with_caution", "do_not_ship", "inconclusive"] as const;
export type Recommendation = (typeof RECOMMENDATIONS)[number];

export const RECOMMENDATION_META: Record<Recommendation, EnumMeta> = {
  ship: {
    label: "Déployer",
    tone: "green",
    icon: "Rocket",
    description: "Candidate meilleure, aucune régression critique.",
  },
  ship_with_caution: {
    label: "Déployer avec prudence",
    tone: "amber",
    icon: "TriangleAlert",
    description: "Meilleure globalement, mais avec des régressions majeures ou des compromis.",
  },
  do_not_ship: {
    label: "Ne pas déployer",
    tone: "red",
    icon: "OctagonX",
    description: "Moins bonne, régression critique ou sécurité dégradée.",
  },
  inconclusive: {
    label: "Non concluant",
    tone: "neutral",
    icon: "CircleHelp",
    description: "Pas assez d'éléments pour conclure.",
  },
};

export const CALIBRATION_STATUSES = ["calibrated", "weak", "uncalibrated", "insufficient_data"] as const;
export type CalibrationStatus = (typeof CALIBRATION_STATUSES)[number];

export const CALIBRATION_STATUS_META: Record<CalibrationStatus, EnumMeta> = {
  calibrated: { label: "Calibré", tone: "green", description: "Kappa ≥ 0,6 et accord ≥ 70 %." },
  weak: { label: "Calibration faible", tone: "amber", description: "Kappa ≥ 0,4." },
  uncalibrated: { label: "Non calibré", tone: "red", description: "Accord insuffisant avec les évaluations humaines." },
  insufficient_data: { label: "Données insuffisantes", tone: "neutral", description: "Moins de 10 paires IA / humain." },
};

/* -------------------------------------------------------------------------- */
/* Jobs                                                                       */
/* -------------------------------------------------------------------------- */

export const JOB_KINDS = ["execute_run", "evaluate_run", "finalize_execution", "finalize_experiment"] as const;
export type JobKind = (typeof JOB_KINDS)[number];

export const JOB_KIND_META: Record<JobKind, EnumMeta> = {
  execute_run: { label: "Exécution d'un run", tone: "blue" },
  evaluate_run: { label: "Évaluation d'un run", tone: "violet" },
  finalize_execution: { label: "Agrégation d'un benchmark", tone: "orange" },
  finalize_experiment: { label: "Comparaison d'une expérience", tone: "pink" },
};

export const JOB_QUEUES = ["execution", "evaluation"] as const;
export type JobQueue = (typeof JOB_QUEUES)[number];

export const JOB_QUEUE_META: Record<JobQueue, EnumMeta> = {
  execution: { label: "Exécution", tone: "blue" },
  evaluation: { label: "Évaluation", tone: "violet" },
};

export const JOB_STATUSES = ["queued", "running", "succeeded", "failed", "cancelled"] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

export const JOB_STATUS_META: Record<JobStatus, EnumMeta> = {
  queued: { label: "En file", tone: "sky" },
  running: { label: "En cours", tone: "blue" },
  succeeded: { label: "Réussi", tone: "green" },
  failed: { label: "Échec", tone: "red" },
  cancelled: { label: "Annulé", tone: "neutral" },
};

/* -------------------------------------------------------------------------- */
/* Personal data (rules)                                                      */
/* -------------------------------------------------------------------------- */

export const PII_TYPES = ["EMAIL", "PHONE", "IBAN", "CARD", "NIR", "IP", "PERSON"] as const;
export type PiiType = (typeof PII_TYPES)[number];

export const PII_TYPE_META: Record<PiiType, EnumMeta> = {
  EMAIL: { label: "E-mail", tone: "blue" },
  PHONE: { label: "Téléphone", tone: "sky" },
  IBAN: { label: "IBAN", tone: "red" },
  CARD: { label: "Carte bancaire", tone: "red" },
  NIR: { label: "NIR", tone: "red", description: "Numéro d'inscription au répertoire (identifiant national)." },
  IP: { label: "Adresse IP", tone: "neutral" },
  PERSON: { label: "Nom de personne", tone: "violet" },
};
