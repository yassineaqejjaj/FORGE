"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Braces, Gavel, Save } from "lucide-react";

import { BackLink, DetailSkeleton } from "@/components/benchmarks/common";
import { DimensionDot } from "@/components/domain/dimension-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { SimpleSelect } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useCurrentUser } from "@/hooks/use-current-user";
import { errorMessage, isApiError } from "@/lib/api/client";
import { useForgeMeta } from "@/lib/api/evaluation-configs";
import { PLACEHOLDER_HELP, useCreateJudge, useCreateJudgeVersion, useJudge, type JudgeDetail } from "@/lib/api/judges";
import { useCredentials } from "@/lib/api/settings";
import { DIMENSION_META, getMeta, JUDGE_PROVIDER_META, JUDGE_PROVIDERS, type JudgeProvider } from "@/lib/enums";
import { slugify } from "@/lib/utils";

const DEFAULT_PLACEHOLDERS = Object.keys(PLACEHOLDER_HELP);
const NO_CREDENTIAL = "__none__";
const KEY_PATTERN = /^[a-z0-9][a-z0-9._-]{1,79}$/;

interface FormState {
  key: string;
  name: string;
  description: string;
  provider: JudgeProvider;
  model: string;
  model_version: string;
  credential_id: string;
  base_url: string;
  temperature: number;
  max_tokens: string;
  weight: string;
  criteria: string[];
  system_prompt: string;
  rubric_template: string;
  enabled: boolean;
}

function fromJudge(j?: JudgeDetail): FormState {
  return {
    key: j?.key ?? "",
    name: j?.name ?? "",
    description: j?.description ?? "",
    provider: (j?.provider as JudgeProvider) ?? "anthropic",
    model: j?.model ?? "",
    model_version: j?.model_version ?? "",
    credential_id: j?.credential_id ?? "",
    base_url: j?.base_url ?? "",
    temperature: j?.temperature ?? 0,
    max_tokens: String(j?.max_tokens ?? 1500),
    weight: String(j?.weight ?? 1),
    criteria: j?.criteria ?? [],
    system_prompt: j?.system_prompt ?? "",
    rubric_template: j?.rubric_template ?? "",
    enabled: j?.enabled ?? true,
  };
}

function CredentialField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { hasRole } = useCurrentUser();
  const isAdmin = hasRole("admin");
  const credentials = useCredentials(isAdmin);
  if (!isAdmin || credentials.isError) {
    return (
      <Field
        id="judge-credential"
        label="Identifiant fournisseur"
        hint="Identifiant (UUID) d'un identifiant fournisseur ; seuls les administrateurs peuvent lister les identifiants. Vide = clé de l'environnement."
      >
        <Input id="judge-credential" className="font-mono" value={value} onChange={(e) => onChange(e.target.value.trim())} placeholder="UUID (optionnel)" />
      </Field>
    );
  }
  return (
    <Field id="judge-credential" label="Identifiant fournisseur" hint="Le secret est déchiffré uniquement dans les workers, au moment de l'appel.">
      <SimpleSelect
        id="judge-credential"
        placeholder={credentials.isPending ? "Chargement…" : "Aucun (clé de l'environnement)"}
        value={value || NO_CREDENTIAL}
        onValueChange={(v) => onChange(v === NO_CREDENTIAL ? "" : v)}
        options={[
          { value: NO_CREDENTIAL, label: "Aucun (clé de l'environnement)" },
          ...(credentials.data ?? []).map((c) => ({
            value: c.id,
            label: c.name,
            description: `${c.kind}${c.secret_hint ? ` · ${c.secret_hint}` : ""}${c.base_url ? ` · ${c.base_url}` : ""}`,
          })),
        ]}
      />
    </Field>
  );
}

/** Insert `{placeholder}` at the caret of a textarea. */
function insertAtCaret(el: HTMLTextAreaElement | null, text: string, current: string, set: (v: string) => void) {
  if (!el) {
    set(current + text);
    return;
  }
  const start = el.selectionStart ?? current.length;
  const end = el.selectionEnd ?? current.length;
  const next = current.slice(0, start) + text + current.slice(end);
  set(next);
  requestAnimationFrame(() => {
    el.focus();
    el.setSelectionRange(start + text.length, start + text.length);
  });
}

export interface JudgeFormProps {
  /** New version of this judge when provided, else create a judge (v1). */
  judgeId?: string;
}

/** Create a judge or a new immutable version of a judge (maintainer). */
export function JudgeForm({ judgeId }: JudgeFormProps) {
  const router = useRouter();
  const judge = useJudge(judgeId);
  const meta = useForgeMeta();
  const create = useCreateJudge();
  const createVersion = useCreateJudgeVersion(judgeId ?? "");
  const mutation = judgeId ? createVersion : create;
  const [form, setForm] = React.useState<FormState>(() => fromJudge());
  const [loaded, setLoaded] = React.useState(!judgeId);
  const [keyTouched, setKeyTouched] = React.useState(false);
  const [submitted, setSubmitted] = React.useState(false);
  const rubricRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    if (judge.data && !loaded) {
      setForm(fromJudge(judge.data));
      setLoaded(true);
    }
  }, [judge.data, loaded]);

  const update = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((f) => ({ ...f, [k]: v }));
  const judgedCriteria = (meta.data?.criteria ?? []).filter((c) => c.judged);
  const placeholders = judge.data?.placeholders?.length ? judge.data.placeholders : DEFAULT_PLACEHOLDERS;
  const maxTokens = Number(form.max_tokens);
  const weight = Number(form.weight);
  const heuristic = form.provider === "heuristic";

  const errors = {
    key: !judgeId && !KEY_PATTERN.test(form.key) ? "2 à 80 caractères : minuscules, chiffres, « . », « _ », « - »." : undefined,
    name: !form.name.trim() ? "Le nom est obligatoire." : undefined,
    model: !form.model.trim() ? "Le modèle est obligatoire." : undefined,
    max_tokens: !Number.isInteger(maxTokens) || maxTokens < 1 || maxTokens > 128000 ? "Entre 1 et 128 000." : undefined,
    weight: !Number.isFinite(weight) || weight < 0 ? "Poids positif ou nul." : undefined,
    credential_id:
      form.credential_id && !/^[0-9a-f-]{36}$/i.test(form.credential_id) ? "UUID invalide." : undefined,
  };
  const valid = !Object.values(errors).some(Boolean);
  const fieldErrors = isApiError(mutation.error) ? mutation.error.fieldErrors : {};

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (!valid) return;
    const behaviour = {
      provider: form.provider,
      model: form.model.trim(),
      model_version: form.model_version.trim() || null,
      temperature: form.temperature,
      max_tokens: maxTokens,
      system_prompt: form.system_prompt,
      rubric_template: form.rubric_template,
      criteria: form.criteria,
      weight,
      base_url: form.base_url.trim() || null,
      credential_id: form.credential_id || null,
    };
    if (judgeId) {
      const res = await createVersion.mutateAsync({ ...behaviour, name: form.name.trim(), description: form.description });
      router.push(`/judges/${res.id}`);
    } else {
      const res = await create.mutateAsync({
        ...behaviour,
        key: form.key,
        name: form.name.trim(),
        description: form.description,
        enabled: form.enabled,
      });
      router.push(`/judges/${res.id}`);
    }
  };

  if (judgeId && judge.isPending) return <DetailSkeleton />;
  if (judgeId && judge.isError) return <ErrorState error={judge.error} onRetry={() => void judge.refetch()} />;

  return (
    <>
      <BackLink href={judgeId ? `/judges/${judgeId}` : "/judges"}>{judgeId ? judge.data?.name : "Juges"}</BackLink>
      <PageHeader
        eyebrow="Juges"
        icon={<Gavel />}
        title={judgeId ? `Nouvelle version de ${judge.data?.name ?? "juge"}` : "Nouveau juge"}
        description={
          judgeId
            ? `Les versions sont immuables : enregistrer crée la v${((judge.data?.versions ?? []).reduce((m, v) => Math.max(m, v.version), 0) ?? 0) + 1}. Une version identique à la dernière est refusée.`
            : "Un juge évalue chaque critère d'un run avec une justification, une confiance et des preuves."
        }
      />
      <form onSubmit={submit} noValidate className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Identité</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Field id="judge-name" label="Nom" required error={submitted ? errors.name : fieldErrors.name}>
                <Input
                  id="judge-name"
                  value={form.name}
                  invalid={submitted && Boolean(errors.name)}
                  onChange={(e) => {
                    update("name", e.target.value);
                    if (!judgeId && !keyTouched) update("key", slugify(e.target.value, 80));
                  }}
                />
              </Field>
              <Field id="judge-key" label="Clé" required={!judgeId} hint={judgeId ? "Fixe pour toutes les versions" : "Identifiant stable, ex. claude-judge"} error={submitted ? errors.key : fieldErrors.key}>
                <Input
                  id="judge-key"
                  className="font-mono"
                  value={form.key}
                  disabled={Boolean(judgeId)}
                  invalid={submitted && Boolean(errors.key)}
                  onChange={(e) => {
                    update("key", e.target.value);
                    setKeyTouched(true);
                  }}
                />
              </Field>
              <Field id="judge-description" label="Description" className="sm:col-span-2">
                <Textarea id="judge-description" rows={2} value={form.description} onChange={(e) => update("description", e.target.value)} />
              </Field>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Prompt système</CardTitle>
              <CardDescription>Consignes de l&apos;évaluateur (impartialité, preuves, format JSON).</CardDescription>
            </CardHeader>
            <CardContent>
              <Textarea
                aria-label="Prompt système"
                rows={10}
                className="font-mono text-[12.5px]"
                value={form.system_prompt}
                onChange={(e) => update("system_prompt", e.target.value)}
                placeholder={heuristic ? "Non utilisé par le juge heuristique" : "Tu es un évaluateur expert, rigoureux et impartial…"}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Braces className="size-4 text-muted-foreground" aria-hidden />
                Grille d&apos;évaluation
              </CardTitle>
              <CardDescription>
                Gabarit rendu avec les variables ci-dessous (cliquez pour insérer). Vide = grille par défaut de FORGE.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Variables disponibles">
                {placeholders.map((p) => (
                  <SimpleTooltip key={p} content={PLACEHOLDER_HELP[p] ?? p}>
                    <button
                      type="button"
                      className="rounded-md border border-border bg-muted/50 px-1.5 py-0.5 font-mono text-[11.5px] text-foreground transition-colors hover:border-brand hover:bg-brand-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onClick={() => insertAtCaret(rubricRef.current, `{${p}}`, form.rubric_template, (v) => update("rubric_template", v))}
                    >
                      {`{${p}}`}
                    </button>
                  </SimpleTooltip>
                ))}
              </div>
              <Textarea
                ref={rubricRef}
                aria-label="Grille d'évaluation"
                rows={16}
                className="font-mono text-[12.5px]"
                value={form.rubric_template}
                onChange={(e) => update("rubric_template", e.target.value)}
                placeholder={"# Scénario : {scenario_name}\n…\n## Sortie finale de l'agent\n{output}\n\n## Critères à évaluer\n{criteria}"}
              />
            </CardContent>
          </Card>
        </div>

        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Modèle</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <Field id="judge-provider" label="Fournisseur" required>
                <SimpleSelect
                  id="judge-provider"
                  value={form.provider}
                  onValueChange={(v) => update("provider", v)}
                  options={JUDGE_PROVIDERS.map((p) => ({ value: p, label: JUDGE_PROVIDER_META[p].label, description: JUDGE_PROVIDER_META[p].description }))}
                />
              </Field>
              <Field id="judge-model" label="Modèle" required error={submitted ? errors.model : fieldErrors.model}>
                <Input
                  id="judge-model"
                  value={form.model}
                  invalid={submitted && Boolean(errors.model)}
                  onChange={(e) => update("model", e.target.value)}
                  placeholder={heuristic ? "heuristic-v1" : "claude-sonnet-4-5 / gpt-4.1"}
                />
              </Field>
              <Field id="judge-model-version" label="Version du modèle" hint="Optionnel (date de snapshot…)">
                <Input id="judge-model-version" value={form.model_version} onChange={(e) => update("model_version", e.target.value)} />
              </Field>
              {!heuristic ? (
                <>
                  <CredentialField value={form.credential_id} onChange={(v) => update("credential_id", v)} />
                  {submitted && errors.credential_id ? <p className="-mt-2 text-xs text-destructive">{errors.credential_id}</p> : null}
                  <Field id="judge-base-url" label="URL de base" hint="Endpoint OpenAI-compatible (vide = défaut du fournisseur ou de l'identifiant)">
                    <Input id="judge-base-url" value={form.base_url} onChange={(e) => update("base_url", e.target.value)} placeholder="https://…/v1" />
                  </Field>
                </>
              ) : null}
              <Field id="judge-temperature" label="Température" labelAside={form.temperature.toFixed(2).replace(".", ",")}>
                <Slider
                  id="judge-temperature"
                  aria-label="Température"
                  min={0}
                  max={2}
                  step={0.05}
                  value={[form.temperature]}
                  onValueChange={([v]) => update("temperature", v ?? 0)}
                />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field id="judge-max-tokens" label="Tokens max." error={submitted ? errors.max_tokens : undefined}>
                  <Input id="judge-max-tokens" type="number" min={1} value={form.max_tokens} onChange={(e) => update("max_tokens", e.target.value)} />
                </Field>
                <Field id="judge-weight" label="Poids" hint="Agrégation pondérée" error={submitted ? errors.weight : undefined}>
                  <Input id="judge-weight" type="number" min={0} step={0.1} value={form.weight} onChange={(e) => update("weight", e.target.value)} />
                </Field>
              </div>
              {!judgeId ? (
                <label className="flex items-center justify-between gap-2 text-[13px]">
                  Activé dès la création
                  <Switch checked={form.enabled} onCheckedChange={(c) => update("enabled", c)} />
                </label>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Critères jugés</CardTitle>
              <CardDescription>Aucun = tous les critères jugés du scénario et de la configuration (hors coût, latence, robustesse).</CardDescription>
            </CardHeader>
            <CardContent>
              {meta.isPending ? (
                <p className="text-[13px] text-muted-foreground">Chargement…</p>
              ) : (
                <ul className="grid max-h-80 gap-1 overflow-y-auto">
                  {judgedCriteria.map((c) => {
                    const checked = form.criteria.includes(c.key);
                    return (
                      <li key={c.key}>
                        <label className="flex cursor-pointer items-start gap-2 rounded-md px-1.5 py-1 text-[13px] hover:bg-muted/60">
                          <Checkbox
                            className="mt-0.5"
                            checked={checked}
                            onCheckedChange={() =>
                              update("criteria", checked ? form.criteria.filter((k) => k !== c.key) : [...form.criteria, c.key])
                            }
                          />
                          <span className="grid">
                            <span className="flex items-center gap-1.5">
                              <DimensionDot dimension={c.dimension} />
                              {c.name}
                            </span>
                            <span className="font-mono text-[11px] text-muted-foreground">
                              {c.key} · {getMeta(DIMENSION_META, c.dimension).label}
                            </span>
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              )}
              {form.criteria.length ? (
                <div className="mt-3 flex flex-wrap items-center gap-1">
                  <Badge tone="orange">{form.criteria.length} sélectionné(s)</Badge>
                  <Button variant="ghost" size="xs" onClick={() => update("criteria", [])}>
                    Effacer
                  </Button>
                </div>
              ) : null}
            </CardContent>
          </Card>

          {mutation.error ? <Alert tone="red">{errorMessage(mutation.error)}</Alert> : null}
          <div className="flex flex-wrap justify-end gap-2">
            <Button asChild variant="secondary">
              <Link href={judgeId ? `/judges/${judgeId}` : "/judges"}>Annuler</Link>
            </Button>
            <Button type="submit" loading={mutation.isPending} leftIcon={<Save aria-hidden />}>
              {judgeId ? "Créer la version" : "Créer le juge"}
            </Button>
          </div>
        </div>
      </form>
    </>
  );
}
