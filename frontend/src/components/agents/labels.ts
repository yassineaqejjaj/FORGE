/** French labels of agent version fields (diff tables, validation summaries). */
export const AGENT_VERSION_FIELD_LABELS: Record<string, string> = {
  version: "Libellé de version",
  adapter_kind: "Type d'adapter",
  endpoint: "Endpoint",
  model: "Modèle",
  prompt: "Prompt versionné",
  system_prompt: "Prompt système",
  prompt_name: "Nom du prompt",
  tools: "Outils",
  tool_configuration: "Configuration d'outils",
  tools_name: "Nom de la configuration d'outils",
  context_config: "Contexte",
  memory_config: "Mémoire",
  orchestration_config: "Orchestration",
  adapter_config: "Configuration de l'adapter",
  credential_id: "Identifiant fournisseur",
  budget: "Budget",
  max_concurrency: "Concurrence maximale",
  metadata: "Métadonnées",
  changelog: "Journal des modifications",
};

export function agentFieldLabel(field: string): string {
  const head = field.split(/[.[]/)[0] ?? field;
  const base = AGENT_VERSION_FIELD_LABELS[head] ?? head;
  return head === field ? base : `${base} (${field.slice(head.length).replace(/^\./, "")})`;
}

/** "sha256:f560eafc…" → "f560eafc7376". */
export function shortHash(hash: string | null | undefined, length = 12): string {
  if (!hash) return "—";
  const raw = hash.includes(":") ? hash.split(":").pop() ?? hash : hash;
  return raw.slice(0, length);
}

/** `{{variable}}` placeholders of a prompt (display only). */
export function promptVariables(prompt: string): string[] {
  const found = new Set<string>();
  for (const m of prompt.matchAll(/\{\{\s*([\w.-]+)\s*\}\}/g)) if (m[1]) found.add(m[1]);
  return [...found];
}
