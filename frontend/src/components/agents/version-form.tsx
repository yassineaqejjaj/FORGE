"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Braces, Brain, CopyPlus, Cpu, GitBranchPlus, KeyRound, Network, Server, Wallet, Wrench } from "lucide-react";

import { useBreadcrumbLabel } from "@/components/layout/shell-context";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/ui/page-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useCurrentUser } from "@/hooks/use-current-user";
import {
  useAgent,
  useAgentVersion,
  useAgentVersions,
  useCreateAgentVersion,
  useCredentials,
  type AgentVersion,
} from "@/lib/api/agents";
import { isApiError } from "@/lib/api/client";
import { useMeta, type MetaAdapter } from "@/lib/api/scenarios";
import { ADAPTER_KIND_META, CONTEXT_SOURCE_META, CONTEXT_SOURCES, getMeta, type AdapterKind, type ContextSource } from "@/lib/enums";
import { formatDate, plural } from "@/lib/format";
import { cn } from "@/lib/utils";

import { fieldError } from "./kit/field-errors";
import { JsonField, toJsonText } from "./kit/json-field";
import { roleRequirement } from "./kit/role-button";
import { useUrlState } from "./kit/use-url-state";
import { agentFieldLabel, promptVariables } from "./labels";
import {
  buildVersionPayload,
  changedKeys,
  emptyFormState,
  formStateFromVersion,
  getJsonKey,
  invalidJsonFields,
  setJsonKey,
  suggestNextLabel,
  type VersionFormState,
} from "./version-form-model";

const STRIP = ["body."] as const;

const TOOLS_PLACEHOLDER = `[
  {
    "name": "search_docs",
    "description": "Recherche dans la base documentaire",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
  }
]`;

function Section({
  icon,
  title,
  description,
  children,
  aside,
}: {
  icon: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  aside?: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-start gap-3">
        <div className="grid min-w-0 flex-1 gap-1">
          <CardTitle className="flex items-center gap-2 [&_svg]:size-4 [&_svg]:text-muted-foreground">
            {icon}
            {title}
          </CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </div>
        {aside}
      </CardHeader>
      <CardContent className="grid gap-4">{children}</CardContent>
    </Card>
  );
}

/** New version page: base selection (URL `?base=`), then the editor. */
export function NewVersionView({ agentId }: { agentId: string }) {
  const agent = useAgent(agentId);
  const versions = useAgentVersions(agentId);
  const url = useUrlState();
  const baseId = url.get("base");
  const base = useAgentVersion(baseId || undefined);
  const { hasRole, isLoading } = useCurrentUser();
  useBreadcrumbLabel(agentId, agent.data?.name);
  useBreadcrumbLabel("versions", "Versions");
  useBreadcrumbLabel("new", "Nouvelle version");

  const list = versions.data ?? [];
  const latest = list[0];

  if (agent.isError) return <ErrorState error={agent.error} onRetry={() => void agent.refetch()} />;
  if (!isLoading && !hasRole("editor")) {
    return <ErrorState error={new Error(roleRequirement("editor"))} title="Accès réservé" />;
  }

  return (
    <>
      <PageHeader
        eyebrow={
          agent.data ? (
            <Link href={`/agents/${agentId}`} className="hover:underline">
              {agent.data.name}
            </Link>
          ) : (
            "Agent"
          )
        }
        title="Nouvelle version"
        icon={<GitBranchPlus />}
        description="Les versions sont immuables : la nouvelle version reçoit sa propre empreinte de contenu. Une version identique à la dernière est refusée."
      />
      <Card className="mb-4">
        <CardContent className="grid gap-3 pt-5 sm:grid-cols-[auto_minmax(0,1fr)] sm:items-end">
          <div className="grid gap-1.5">
            <Label>Point de départ</Label>
            <SegmentedControl
              aria-label="Point de départ"
              value={baseId ? "base" : "scratch"}
              onValueChange={(v) => url.set({ base: v === "base" ? (latest?.id ?? null) : null })}
              options={[
                { value: "scratch", label: "Depuis zéro" },
                { value: "base", label: "Basée sur une version", disabled: list.length === 0 },
              ]}
            />
          </div>
          {baseId ? (
            <Field id="base-version" label="Version de base" hint="Seuls les champs modifiés sont envoyés ; tout le reste est repris de cette version.">
              <SimpleSelect
                id="base-version"
                value={baseId}
                onValueChange={(v) => url.set({ base: v })}
                options={list.map((v) => ({
                  value: v.id,
                  label: `v${v.version}`,
                  description: `${formatDate(v.created_at)}${v.changelog ? ` · ${v.changelog.slice(0, 60)}` : ""}`,
                }))}
                className="sm:max-w-sm"
              />
            </Field>
          ) : null}
        </CardContent>
      </Card>

      {baseId && base.isError ? (
        <ErrorState error={base.error} onRetry={() => void base.refetch()} />
      ) : (baseId && base.isPending) || versions.isPending ? (
        <div className="grid gap-4">
          <Skeleton className="h-64 w-full rounded-xl" />
          <Skeleton className="h-64 w-full rounded-xl" />
        </div>
      ) : (
        <VersionEditor
          key={baseId || "scratch"}
          agentId={agentId}
          base={baseId ? (base.data ?? null) : null}
          latestLabel={latest?.version ?? null}
        />
      )}
    </>
  );
}

function VersionEditor({ agentId, base, latestLabel }: { agentId: string; base: AgentVersion | null; latestLabel: string | null }) {
  const router = useRouter();
  const meta = useMeta();
  const { hasRole } = useCurrentUser();
  const isAdmin = hasRole("admin");
  const credentials = useCredentials(isAdmin);
  const create = useCreateAgentVersion(agentId);
  const initial = React.useMemo(() => (base ? formStateFromVersion(base) : emptyFormState()), [base]);
  const [state, setState] = React.useState<VersionFormState>(initial);
  const error = create.error;
  const errors = isApiError(error) ? error.errors : [];
  const fe = (path: string, deep = false) => fieldError(errors, path, { deep, strip: STRIP });

  const set = <K extends keyof VersionFormState>(key: K, value: VersionFormState[K]) => setState((s) => ({ ...s, [key]: value }));
  const setModel = (key: keyof VersionFormState["model"], value: string) => setState((s) => ({ ...s, model: { ...s.model, [key]: value } }));
  const setOrbit = <K extends keyof VersionFormState["orbit"]>(key: K, value: VersionFormState["orbit"][K]) =>
    setState((s) => ({ ...s, orbit: { ...s.orbit, [key]: value } }));
  const setBudget = (key: keyof VersionFormState["budget"], value: string) => setState((s) => ({ ...s, budget: { ...s.budget, [key]: value } }));

  const adapters = meta.data?.adapters ?? [];
  const adapter: MetaAdapter | undefined = adapters.find((a) => a.kind === state.adapter_kind);
  const requiresModel = adapter?.requires_model ?? false;
  const requiresEndpoint = adapter?.requires_endpoint ?? false;
  const changed = changedKeys(state, base ? initial : null);
  const invalid = invalidJsonFields(state);
  const suggestion = suggestNextLabel(latestLabel);
  const vars = promptVariables(state.system_prompt);
  const nothingChanged = Boolean(base) && changed.length === 0;
  const canSubmit = invalid.length === 0 && !create.isPending && !nothingChanged;

  React.useEffect(() => {
    if (requiresModel && !state.useModel) setState((s) => ({ ...s, useModel: true }));
  }, [requiresModel, state.useModel]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    const body = buildVersionPayload(state, base ? { id: base.id, state: initial } : null);
    create.mutate(body, {
      onSuccess: (v) => {
        toast.success(`Version ${v.version} créée`, { description: `Empreinte ${v.content_hash.slice(7, 19)}` });
        router.push(`/agents/${agentId}/versions/${v.id}`);
      },
      onError: () => window.scrollTo({ top: 0, behavior: "smooth" }),
    });
  };

  const adapterQuickFields = (() => {
    const quick = (key: string, label: string, hint?: string, placeholder?: string) => (
      <Field key={key} id={`adapter-${key}`} label={label} hint={hint} error={fe(`adapter_config.${key}`)}>
        <Input
          id={`adapter-${key}`}
          value={getJsonKey(state.adapter_config, key)}
          onChange={(e) => set("adapter_config", setJsonKey(state.adapter_config, key, e.target.value))}
          placeholder={placeholder}
          className="font-mono"
        />
      </Field>
    );
    switch (state.adapter_kind) {
      case "custom_api":
        return [
          <Field key="mode" id="adapter-mode" label="Mode" hint="forge : FORGE Agent Protocol · mapped : gabarit de requête et chemins JSON.">
            <SimpleSelect
              id="adapter-mode"
              value={getJsonKey(state.adapter_config, "mode") || "forge"}
              onValueChange={(v) => set("adapter_config", setJsonKey(state.adapter_config, "mode", v === "forge" ? "" : v))}
              options={[
                { value: "forge", label: "FORGE Agent Protocol" },
                { value: "mapped", label: "Requête / réponse mappées" },
              ]}
            />
          </Field>,
          quick("output_path", "Chemin de la réponse (mode mapped)", "Chemin JSON du texte de réponse (défaut output).", "answer"),
        ];
      case "nova":
        return [quick("nova_agent_id", "Identifiant de l'agent NOVA", "Requis.", "product-agent"), quick("base_url", "URL de NOVA", "Sinon celle de l'identifiant ou de l'endpoint.")];
      case "openai":
      case "anthropic":
        return [quick("base_url", "URL de l'API", "Sinon celle de l'identifiant (API compatible OpenAI : vLLM, Ollama, Mistral…).", "https://api.example.com/v1")];
      default:
        return [];
    }
  })();

  const credentialOptions = (() => {
    const kinds = adapter?.credential_kinds ?? [];
    const opts = [{ value: "__none__", label: "Aucun identifiant", description: undefined as string | undefined }];
    if (isAdmin) {
      for (const c of credentials.data ?? []) {
        opts.push({
          value: c.id,
          label: c.name,
          description: `${c.kind}${c.secret_hint ? ` · ${c.secret_hint}` : ""}${kinds.length && !kinds.includes(c.kind) ? " · type non attendu" : ""}`,
        });
      }
    } else if (base?.credential) {
      opts.push({ value: base.credential.id, label: base.credential.name, description: base.credential.kind });
    }
    if (state.credential_id && !opts.some((o) => o.value === state.credential_id)) {
      opts.push({ value: state.credential_id, label: "Identifiant actuel", description: state.credential_id });
    }
    return opts;
  })();

  return (
    <form onSubmit={submit} className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]" noValidate>
      <div className="grid min-w-0 content-start gap-4">
        {error ? (
          error.isConflict ? (
            <Alert tone="amber" title="Version identique">
              {error.detail}. Modifiez au moins un champ de comportement (prompt, modèle, outils, contexte, adapter, budget…).
            </Alert>
          ) : (
            <Alert tone="red" title={errors.length ? `${plural(errors.length, "champ invalide", "champs invalides")}` : "Création impossible"}>
              {errors.length ? (
                <ul className="list-disc pl-4">
                  {errors.map((e, i) => (
                    <li key={i}>
                      <span className="font-medium">{agentFieldLabel(e.field.replace(/^body\./, ""))}</span> : {e.message}
                    </li>
                  ))}
                </ul>
              ) : (
                error.detail
              )}
            </Alert>
          )
        ) : null}

        <Section icon={<Server />} title="Adapter" description={adapter?.description}>
          <div className="grid gap-4 md:grid-cols-2">
            <Field id="adapter-kind" label="Type d'adapter" required error={fe("adapter_kind")}>
              <SimpleSelect<AdapterKind>
                id="adapter-kind"
                value={state.adapter_kind}
                onValueChange={(v) => set("adapter_kind", v)}
                options={(adapters.length ? adapters.map((a) => a.kind) : Object.keys(ADAPTER_KIND_META)).map((k) => ({
                  value: k as AdapterKind,
                  label: adapters.find((a) => a.kind === k)?.label ?? getMeta(ADAPTER_KIND_META, k).label,
                }))}
              />
            </Field>
            <Field
              id="endpoint"
              label="Endpoint"
              required={requiresEndpoint}
              hint={requiresEndpoint ? "URL appelée par FORGE." : "Optionnel pour cet adapter."}
              error={fe("endpoint")}
            >
              <Input
                id="endpoint"
                value={state.endpoint}
                onChange={(e) => set("endpoint", e.target.value)}
                placeholder="https://agents.example.com/run"
                className="font-mono"
                invalid={Boolean(fe("endpoint"))}
              />
            </Field>
            {adapterQuickFields}
          </div>
          <JsonField
            id="adapter-config"
            label="Configuration de l'adapter (JSON)"
            value={state.adapter_config}
            onChange={(v) => set("adapter_config", v)}
            expect="object"
            rows={6}
            error={fe("adapter_config", true)}
            labelAside={
              adapter?.example && "adapter_config" in adapter.example ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="xs"
                  onClick={() => set("adapter_config", toJsonText(adapter.example.adapter_config))}
                >
                  Insérer l&apos;exemple
                </Button>
              ) : undefined
            }
          />
          {adapter && Object.keys(adapter.adapter_config).length ? (
            <details className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs">
              <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">Clés reconnues</summary>
              <dl className="mt-2 grid gap-1.5">
                {Object.entries(adapter.adapter_config).map(([k, doc]) => (
                  <div key={k} className="grid gap-0.5 sm:grid-cols-[12rem_minmax(0,1fr)]">
                    <dt className="font-mono text-foreground">{k}</dt>
                    <dd className="text-muted-foreground">{String(doc)}</dd>
                  </div>
                ))}
              </dl>
            </details>
          ) : null}
        </Section>

        <Section
          icon={<Cpu />}
          title="Modèle"
          description={requiresModel ? "Requis pour cet adapter : FORGE pilote la boucle d'agent avec ce modèle." : "Optionnel : l'agent peut gérer son propre modèle."}
          aside={
            <label className="flex items-center gap-2 text-[13px]">
              <Switch checked={state.useModel} onCheckedChange={(c) => set("useModel", c)} disabled={requiresModel} aria-label="Configurer un modèle" />
              Configurer
            </label>
          }
        >
          {state.useModel ? (
            <div className="grid gap-4 md:grid-cols-3">
              <Field id="model-provider" label="Fournisseur" required error={fe("model.provider")} hint="openai, anthropic, mistral…">
                <Input id="model-provider" value={state.model.provider} onChange={(e) => setModel("provider", e.target.value)} invalid={Boolean(fe("model.provider"))} />
              </Field>
              <Field id="model-model" label="Modèle" required error={fe("model.model")}>
                <Input id="model-model" value={state.model.model} onChange={(e) => setModel("model", e.target.value)} className="font-mono" invalid={Boolean(fe("model.model"))} />
              </Field>
              <Field id="model-version" label="Version du modèle" error={fe("model.model_version")}>
                <Input id="model-version" value={state.model.model_version} onChange={(e) => setModel("model_version", e.target.value)} className="font-mono" />
              </Field>
              <Field id="model-temperature" label="Température" hint="0 à 2" error={fe("model.temperature")}>
                <Input id="model-temperature" inputMode="decimal" value={state.model.temperature} onChange={(e) => setModel("temperature", e.target.value)} invalid={Boolean(fe("model.temperature"))} />
              </Field>
              <Field id="model-top-p" label="Top p" hint="0 à 1" error={fe("model.top_p")}>
                <Input id="model-top-p" inputMode="decimal" value={state.model.top_p} onChange={(e) => setModel("top_p", e.target.value)} invalid={Boolean(fe("model.top_p"))} />
              </Field>
              <Field id="model-max-tokens" label="Tokens max. par appel" error={fe("model.max_tokens")}>
                <Input id="model-max-tokens" inputMode="numeric" value={state.model.max_tokens} onChange={(e) => setModel("max_tokens", e.target.value)} invalid={Boolean(fe("model.max_tokens"))} />
              </Field>
              <Field id="model-seed" label="Graine" error={fe("model.seed")}>
                <Input id="model-seed" inputMode="numeric" value={state.model.seed} onChange={(e) => setModel("seed", e.target.value)} />
              </Field>
              <Field id="model-in-cost" label="Coût entrée / M tokens" error={fe("model.input_cost_per_mtok")} hint="Sinon tarif connu du modèle.">
                <Input id="model-in-cost" inputMode="decimal" value={state.model.input_cost_per_mtok} onChange={(e) => setModel("input_cost_per_mtok", e.target.value)} />
              </Field>
              <Field id="model-out-cost" label="Coût sortie / M tokens" error={fe("model.output_cost_per_mtok")}>
                <Input id="model-out-cost" inputMode="decimal" value={state.model.output_cost_per_mtok} onChange={(e) => setModel("output_cost_per_mtok", e.target.value)} />
              </Field>
              <JsonField
                id="model-params"
                label="Paramètres supplémentaires"
                value={state.model.params}
                onChange={(v) => setModel("params", v)}
                expect="object"
                rows={3}
                className="md:col-span-3"
                error={fe("model.params", true)}
              />
            </div>
          ) : (
            <p className="text-[13px] text-subtle-foreground">Aucune configuration de modèle.</p>
          )}
        </Section>

        <Section
          icon={<Brain />}
          title="Prompt système"
          description="Les variables {{variable}} sont détectées et versionnées avec le prompt."
        >
          <Field id="system-prompt" label="Prompt" error={fe("system_prompt")} labelAside={`${state.system_prompt.length.toLocaleString("fr-FR")} caractères`}>
            <Textarea
              id="system-prompt"
              value={state.system_prompt}
              onChange={(e) => set("system_prompt", e.target.value)}
              rows={14}
              spellCheck={false}
              className="font-mono text-[12.5px]"
              placeholder="Tu es un product manager senior…"
            />
          </Field>
          {vars.length ? (
            <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              Variables détectées :
              {vars.map((v) => (
                <Badge key={v} tone="violet" mono>{`{{${v}}}`}</Badge>
              ))}
            </p>
          ) : null}
          <Field
            id="prompt-name"
            label="Nom du prompt versionné"
            hint="Optionnel : crée la version suivante de ce prompt nommé (ex. product_manager)."
            error={fe("prompt_name")}
          >
            <Input id="prompt-name" value={state.prompt_name} onChange={(e) => set("prompt_name", e.target.value)} className="font-mono sm:max-w-sm" />
          </Field>
        </Section>

        <Section icon={<Wrench />} title="Outils" description="Outils déclarés au modèle (appels résolus par les mocks du scénario quand FORGE pilote la boucle).">
          <JsonField
            id="tools"
            label="Outils (tableau JSON)"
            value={state.tools}
            onChange={(v) => set("tools", v)}
            expect="array"
            rows={8}
            placeholder={TOOLS_PLACEHOLDER}
            error={fe("tools", true)}
          />
          <Field id="tools-name" label="Nom de la configuration d'outils" hint="Optionnel : versionne ces outils sous ce nom." error={fe("tools_name")}>
            <Input id="tools-name" value={state.tools_name} onChange={(e) => set("tools_name", e.target.value)} className="font-mono sm:max-w-sm" />
          </Field>
        </Section>

        <Section icon={<Network />} title="Contexte" description={CONTEXT_SOURCE_META[state.context_source].description}>
          <Field id="context-source" label="Source du contexte" error={fe("context_config.source")}>
            <SimpleSelect<ContextSource>
              id="context-source"
              value={state.context_source}
              onValueChange={(v) => set("context_source", v)}
              options={CONTEXT_SOURCES.map((s) => ({ value: s, label: CONTEXT_SOURCE_META[s].label, description: CONTEXT_SOURCE_META[s].description }))}
              className="sm:max-w-sm"
            />
          </Field>
          {state.context_source === "orbit_snapshot" || state.context_source === "orbit_live" ? (
            <div className="grid gap-4 md:grid-cols-2">
              <Field id="orbit-project" label="Projet ORBIT" required error={fe("context_config.orbit.project")}>
                <Input id="orbit-project" value={state.orbit.project} onChange={(e) => setOrbit("project", e.target.value)} className="font-mono" />
              </Field>
              {state.context_source === "orbit_snapshot" ? (
                <Field id="orbit-snapshot" label="Snapshot" required error={fe("context_config.orbit.snapshot")}>
                  <Input id="orbit-snapshot" value={state.orbit.snapshot} onChange={(e) => setOrbit("snapshot", e.target.value)} className="font-mono" />
                </Field>
              ) : null}
              <Field id="orbit-version" label="Version" hint="Défaut : latest (la version résolue est tracée)." error={fe("context_config.orbit.version")}>
                <Input id="orbit-version" value={state.orbit.version} onChange={(e) => setOrbit("version", e.target.value)} placeholder="latest" className="font-mono" />
              </Field>
              <Field id="orbit-url" label="URL d'ORBIT" hint="Sinon celle de l'identifiant ou de la plateforme." error={fe("context_config.orbit.base_url")}>
                <Input id="orbit-url" value={state.orbit.base_url} onChange={(e) => setOrbit("base_url", e.target.value)} className="font-mono" />
              </Field>
              <Field id="orbit-timeout" label="Délai (secondes)" error={fe("context_config.orbit.timeout_seconds")}>
                <Input id="orbit-timeout" inputMode="decimal" value={state.orbit.timeout_seconds} onChange={(e) => setOrbit("timeout_seconds", e.target.value)} />
              </Field>
              <div className="grid content-end gap-2.5 pb-1">
                <label className="flex items-center gap-2 text-[13px]">
                  <Switch checked={state.orbit.merge} onCheckedChange={(c) => setOrbit("merge", c)} aria-label="Fusionner avec le contexte du scénario" />
                  Fusionner avec le contexte du scénario
                </label>
                <label className="flex items-center gap-2 text-[13px]">
                  <Switch checked={state.orbit.optional} onCheckedChange={(c) => setOrbit("optional", c)} aria-label="ORBIT optionnel" />
                  Continuer si ORBIT est indisponible
                </label>
              </div>
            </div>
          ) : null}
        </Section>

        <Section icon={<Wallet />} title="Budget & exécution" description="Limites appliquées à chaque run (dépassement → erreur BUDGET_EXCEEDED ou TIMEOUT).">
          <div className="grid gap-4 md:grid-cols-3">
            <Field id="budget-tokens" label="Tokens max." hint="Vide : illimité." error={fe("budget.max_tokens")}>
              <Input id="budget-tokens" inputMode="numeric" value={state.budget.max_tokens} onChange={(e) => setBudget("max_tokens", e.target.value)} invalid={Boolean(fe("budget.max_tokens"))} />
            </Field>
            <Field id="budget-cost" label="Coût max." hint="Vide : illimité." error={fe("budget.max_cost")}>
              <Input id="budget-cost" inputMode="decimal" value={state.budget.max_cost} onChange={(e) => setBudget("max_cost", e.target.value)} invalid={Boolean(fe("budget.max_cost"))} />
            </Field>
            <Field id="budget-steps" label="Tours max." hint="Boucle pilotée par FORGE (1 à 100)." error={fe("budget.max_steps")}>
              <Input id="budget-steps" inputMode="numeric" value={state.budget.max_steps} onChange={(e) => setBudget("max_steps", e.target.value)} invalid={Boolean(fe("budget.max_steps"))} />
            </Field>
            <Field id="budget-timeout" label="Délai max. (secondes)" hint="Vide : défaut de la plateforme." error={fe("budget.timeout_seconds")}>
              <Input id="budget-timeout" inputMode="decimal" value={state.budget.timeout_seconds} onChange={(e) => setBudget("timeout_seconds", e.target.value)} invalid={Boolean(fe("budget.timeout_seconds"))} />
            </Field>
            <Field id="max-concurrency" label="Concurrence max." hint="Runs simultanés de cette version." error={fe("max_concurrency")}>
              <Input id="max-concurrency" inputMode="numeric" value={state.max_concurrency} onChange={(e) => set("max_concurrency", e.target.value)} invalid={Boolean(fe("max_concurrency"))} />
            </Field>
          </div>
          <Field
            id="credential"
            label={
              <span className="inline-flex items-center gap-1.5">
                <KeyRound className="size-3.5" aria-hidden /> Identifiant fournisseur
              </span>
            }
            hint={
              isAdmin
                ? adapter?.credential_kinds.length
                  ? `Type attendu : ${adapter.credential_kinds.join(", ")}. Le secret n'est jamais affiché.`
                  : "Le secret n'est jamais affiché."
                : "La liste des identifiants est réservée aux administrateurs : vous pouvez conserver l'identifiant de la version de base ou le retirer."
            }
            error={fe("credential_id")}
          >
            <SimpleSelect
              id="credential"
              value={state.credential_id || "__none__"}
              onValueChange={(v) => set("credential_id", v === "__none__" ? "" : v)}
              options={credentialOptions}
              className="sm:max-w-md"
            />
          </Field>
        </Section>

        <Section icon={<Braces />} title="Avancé" description="Mémoire, orchestration (multi-agents) et métadonnées libres.">
          <div className="grid gap-4 lg:grid-cols-2">
            <JsonField id="memory" label="Mémoire" value={state.memory_config} onChange={(v) => set("memory_config", v)} expect="object" rows={5} error={fe("memory_config", true)} />
            <JsonField
              id="orchestration"
              label="Orchestration"
              value={state.orchestration_config}
              onChange={(v) => set("orchestration_config", v)}
              expect="object"
              rows={5}
              error={fe("orchestration_config", true)}
            />
            <JsonField id="metadata" label="Métadonnées" value={state.metadata} onChange={(v) => set("metadata", v)} expect="object" rows={4} error={fe("metadata", true)} className="lg:col-span-2" />
          </div>
        </Section>
      </div>

      <aside className="grid content-start gap-4 xl:sticky xl:top-20 xl:self-start">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CopyPlus className="size-4 text-muted-foreground" aria-hidden /> Publication
            </CardTitle>
            <CardDescription>{base ? `Basée sur v${base.version}` : "Version créée depuis zéro"}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <Field id="version-label" label="Libellé" hint="Vide : version mineure suivante attribuée automatiquement." error={fe("version")}>
              <Input
                id="version-label"
                value={state.version}
                onChange={(e) => set("version", e.target.value)}
                placeholder={`Auto : ${suggestion}`}
                className="font-mono"
                maxLength={40}
                rightSlot={
                  !state.version ? (
                    <Button type="button" variant="ghost" size="xs" onClick={() => set("version", suggestion)}>
                      {suggestion}
                    </Button>
                  ) : undefined
                }
              />
            </Field>
            <Field id="changelog" label="Journal des modifications" hint="Ce qui change et pourquoi (visible dans la chronologie)." error={fe("changelog")}>
              <Textarea id="changelog" value={state.changelog} onChange={(e) => set("changelog", e.target.value)} rows={4} maxLength={10000} />
            </Field>
            {base ? (
              <div className="grid gap-1.5 text-xs">
                <p className="font-medium text-muted-foreground">Champs modifiés</p>
                {changed.length ? (
                  <div className="flex flex-wrap gap-1">
                    {changed.map((k) => (
                      <Badge key={k} tone="orange">
                        {agentFieldLabel(k)}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <p className="text-subtle-foreground">Aucun pour l&apos;instant : la version serait identique.</p>
                )}
              </div>
            ) : null}
            {invalid.length ? (
              <p className={cn("text-xs font-medium text-destructive")} role="alert">
                JSON invalide : {invalid.join(", ")}
              </p>
            ) : null}
            <Button type="submit" loading={create.isPending} disabled={!canSubmit} leftIcon={<GitBranchPlus aria-hidden />}>
              Créer la version
            </Button>
            <Button asChild variant="ghost">
              <Link href={`/agents/${agentId}`}>Annuler</Link>
            </Button>
          </CardContent>
        </Card>
      </aside>
    </form>
  );
}
