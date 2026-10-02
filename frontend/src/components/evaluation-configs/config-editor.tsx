"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, Save, SlidersHorizontal, Trash2 } from "lucide-react";

import { BackLink, DetailSkeleton } from "@/components/benchmarks/common";
import { DimensionDot } from "@/components/domain/dimension-badge";
import { JudgeProviderBadge } from "@/components/domain/enum-badge";
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage, isApiError } from "@/lib/api/client";
import {
  useCreateEvaluationConfig,
  useCreateEvaluationConfigVersion,
  useEvaluationConfig,
  useEvaluationConfigs,
  useForgeMeta,
  type ConfigBehaviourInput,
  type EvaluationConfigDetail,
  type GateSpecValue,
  type NormalizationValue,
} from "@/lib/api/evaluation-configs";
import { useJudges } from "@/lib/api/judges";
import { AGGREGATION_METHOD_META, AGGREGATION_METHODS, type AggregationMethod } from "@/lib/enums";
import { slugify } from "@/lib/utils";
import { AGGREGATION_HELP, asGate, NORMALIZATION_FIELDS } from "./config-helpers";
import { gateError, gatePayload, GatesBuilder } from "./gates-builder";
import { PreviewPanel } from "./preview-panel";
import { toFractions, toPercents, WeightsEditor, type WeightPercents } from "./weights-editor";

const KEY_PATTERN = /^[a-z0-9][a-z0-9._-]{1,79}$/;

interface EditorState {
  key: string;
  name: string;
  description: string;
  is_default: boolean;
  weights: WeightPercents;
  criterionWeights: Array<{ key: string; weight: string }>;
  normalization: Record<string, string>;
  gates: GateSpecValue[];
  judgeIds: string[];
  method: AggregationMethod;
  aggWeights: Record<string, string>;
  expression: string;
  criteria: string[];
  rulesJson: string;
  useHuman: boolean;
  passThreshold: string;
}

function fromConfig(c?: EvaluationConfigDetail): EditorState {
  const norm = (c?.normalization ?? {}) as NormalizationValue;
  const agg = (c?.aggregation ?? {}) as { method?: string; weights?: Record<string, number>; expression?: string | null };
  return {
    key: c?.key ?? "",
    name: c?.name ?? "",
    description: c?.description ?? "",
    is_default: c?.is_default ?? false,
    weights: toPercents(
      c?.dimension_weights ?? { quality: 0.3, coherence: 0.15, reasoning: 0.1, safety: 0.2, robustness: 0.05, cost: 0.05, latency: 0.05, ux: 0.1 },
    ),
    criterionWeights: Object.entries(c?.criterion_weights ?? {}).map(([key, w]) => ({ key, weight: String(w) })),
    normalization: Object.fromEntries(
      NORMALIZATION_FIELDS.map((f) => [f.key, norm[f.key] === undefined || norm[f.key] === null ? "" : String(norm[f.key])]),
    ),
    gates: (c?.gates ?? []).map(asGate),
    judgeIds: c?.judge_ids ?? [],
    method: (AGGREGATION_METHODS as readonly string[]).includes(agg.method ?? "") ? (agg.method as AggregationMethod) : "mean",
    aggWeights: Object.fromEntries(Object.entries(agg.weights ?? {}).map(([k, v]) => [k, String(v)])),
    expression: agg.expression ?? "",
    criteria: c?.criteria ?? [],
    rulesJson: JSON.stringify(c?.rules ?? [], null, 2),
    useHuman: c?.use_human_scores ?? false,
    passThreshold: String(c?.pass_threshold ?? 70),
  };
}

function parseRules(json: string): { value: Record<string, unknown>[] | null; error: string | null } {
  try {
    const v: unknown = JSON.parse(json || "[]");
    if (!Array.isArray(v) || !v.every((x) => x && typeof x === "object" && !Array.isArray(x))) {
      return { value: null, error: "Un tableau JSON d'objets règle est attendu." };
    }
    return { value: v as Record<string, unknown>[], error: null };
  } catch (e) {
    return { value: null, error: `JSON invalide : ${(e as Error).message}` };
  }
}

function buildBehaviour(s: EditorState, rules: Record<string, unknown>[]): ConfigBehaviourInput {
  const normalization: Record<string, number> = {};
  for (const f of NORMALIZATION_FIELDS) {
    const raw = s.normalization[f.key];
    if (raw !== undefined && raw !== "") normalization[f.key] = Number(raw);
  }
  return {
    dimension_weights: toFractions(s.weights),
    criterion_weights: Object.fromEntries(s.criterionWeights.filter((r) => r.key).map((r) => [r.key, Number(r.weight)])),
    normalization,
    gates: s.gates.map(gatePayload),
    judge_ids: s.judgeIds,
    aggregation: {
      method: s.method,
      weights: s.method === "weighted" ? Object.fromEntries(Object.entries(s.aggWeights).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)])) : {},
      expression: s.method === "custom" ? s.expression.trim() : null,
    },
    criteria: s.criteria,
    rules,
    use_human_scores: s.useHuman,
    pass_threshold: Number(s.passThreshold),
  };
}

function JudgesPicker({ value, onChange, pinned }: { value: string[]; onChange: (v: string[]) => void; pinned?: EvaluationConfigDetail["judges"] }) {
  const judges = useJudges({ page_size: 200, latest_only: true });
  const list = judges.data?.items ?? [];
  const extra = (pinned ?? []).filter((p) => !list.some((j) => j.id === p.id));
  const rows = [
    ...list.map((j) => ({ id: j.id, key: j.key, name: j.name, version: j.version, provider: j.provider, model: j.model, enabled: j.enabled, latest: true })),
    ...extra.map((j) => ({ id: j.id, key: j.key, name: j.name, version: j.version, provider: j.provider, model: j.model, enabled: j.enabled, latest: j.is_latest })),
  ];
  return (
    <ul className="grid gap-1">
      {rows.map((j) => {
        const checked = value.includes(j.id);
        return (
          <li key={j.id}>
            <label className="flex cursor-pointer flex-wrap items-center gap-2 rounded-md px-1.5 py-1.5 text-[13px] hover:bg-muted/60">
              <Checkbox checked={checked} onCheckedChange={() => onChange(checked ? value.filter((x) => x !== j.id) : [...value, j.id])} />
              <span className="font-medium">{j.name}</span>
              <Badge variant="outline">v{j.version}</Badge>
              <JudgeProviderBadge value={j.provider} />
              <span className="text-xs text-muted-foreground">{j.model}</span>
              {!j.latest ? <Badge tone="amber">Ancienne version</Badge> : null}
              {!j.enabled ? <Badge tone="neutral">Désactivé</Badge> : null}
            </label>
          </li>
        );
      })}
      {judges.isPending ? <li className="text-[13px] text-muted-foreground">Chargement…</li> : null}
    </ul>
  );
}

/** Create a configuration or a new immutable version (maintainer). */
export function ConfigEditor({ configId }: { configId?: string }) {
  const router = useRouter();
  const source = useEvaluationConfig(configId);
  const meta = useForgeMeta();
  const fallbackConfigs = useEvaluationConfigs({ page_size: 50, latest_only: true });
  const create = useCreateEvaluationConfig();
  const createVersion = useCreateEvaluationConfigVersion(configId ?? "");
  const mutation = configId ? createVersion : create;
  const [state, setState] = React.useState<EditorState>(() => fromConfig());
  const [initialWeights, setInitialWeights] = React.useState<WeightPercents | undefined>();
  const [loaded, setLoaded] = React.useState(!configId);
  const [keyTouched, setKeyTouched] = React.useState(false);
  const [submitted, setSubmitted] = React.useState(false);

  React.useEffect(() => {
    if (source.data && !loaded) {
      const s = fromConfig(source.data);
      setState(s);
      setInitialWeights(s.weights);
      setLoaded(true);
    }
  }, [source.data, loaded]);

  const set = <K extends keyof EditorState>(k: K, v: EditorState[K]) => setState((s) => ({ ...s, [k]: v }));
  const rules = parseRules(state.rulesJson);
  const threshold = Number(state.passThreshold);
  const errors = {
    key: !configId && !KEY_PATTERN.test(state.key) ? "2 à 80 caractères : minuscules, chiffres, « . », « _ », « - »." : undefined,
    name: !state.name.trim() ? "Le nom est obligatoire." : undefined,
    threshold: !Number.isFinite(threshold) || threshold < 0 || threshold > 100 ? "Entre 0 et 100." : undefined,
    rules: rules.error ?? undefined,
    gates: state.gates.some((g) => gateError(g)) ? "Corrigez les garde-fous." : undefined,
    expression: state.method === "custom" && !state.expression.trim() ? "Expression obligatoire." : undefined,
    criterionWeights: state.criterionWeights.some((r) => r.key && (!Number.isFinite(Number(r.weight)) || Number(r.weight) < 0))
      ? "Poids de critère invalide."
      : undefined,
  };
  const valid = !Object.values(errors).some(Boolean);
  const behaviour = rules.value ? buildBehaviour(state, rules.value) : undefined;
  const previewConfigId = configId ?? fallbackConfigs.data?.items.find((c) => c.is_default)?.id ?? fallbackConfigs.data?.items[0]?.id;
  const judgedCriteria = (meta.data?.criteria ?? []).filter((c) => c.judged);
  const fieldErrors = isApiError(mutation.error) ? mutation.error.fieldErrors : {};
  const pinnedJudges = source.data?.judges;
  const judgeKeys = Array.from(new Set((pinnedJudges ?? []).map((j) => j.key)));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (!valid || !behaviour) return;
    if (configId) {
      const res = await createVersion.mutateAsync({
        ...behaviour,
        name: state.name.trim(),
        description: state.description,
        is_default: state.is_default,
      });
      router.push(`/evaluation-configs/${res.id}`);
    } else {
      const res = await create.mutateAsync({
        ...behaviour,
        dimension_weights: behaviour.dimension_weights ?? {},
        key: state.key,
        name: state.name.trim(),
        description: state.description,
        is_default: state.is_default,
      });
      router.push(`/evaluation-configs/${res.id}`);
    }
  };

  if (configId && source.isPending) return <DetailSkeleton />;
  if (configId && source.isError) return <ErrorState error={source.error} onRetry={() => void source.refetch()} />;

  return (
    <>
      <BackLink href={configId ? `/evaluation-configs/${configId}` : "/evaluation-configs"}>
        {configId ? source.data?.name : "Configurations"}
      </BackLink>
      <PageHeader
        eyebrow="Configurations d'évaluation"
        icon={<SlidersHorizontal />}
        title={configId ? `Nouvelle version de ${source.data?.name ?? ""}` : "Nouvelle configuration"}
        description="Les versions sont immuables : les runs déjà évalués gardent leur configuration (manifeste). Une version identique à la dernière est refusée."
      />
      <form onSubmit={submit} noValidate className="grid gap-4">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div className="grid content-start gap-4">
            <Card>
              <CardHeader>
                <CardTitle>Identité</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                <Field id="cfg-name" label="Nom" required error={submitted ? errors.name : fieldErrors.name}>
                  <Input
                    id="cfg-name"
                    value={state.name}
                    invalid={submitted && Boolean(errors.name)}
                    onChange={(e) => {
                      set("name", e.target.value);
                      if (!configId && !keyTouched) set("key", slugify(e.target.value, 80));
                    }}
                  />
                </Field>
                <Field id="cfg-key" label="Clé" required={!configId} hint={configId ? "Fixe pour toutes les versions" : undefined} error={submitted ? errors.key : fieldErrors.key}>
                  <Input
                    id="cfg-key"
                    className="font-mono"
                    disabled={Boolean(configId)}
                    value={state.key}
                    invalid={submitted && Boolean(errors.key)}
                    onChange={(e) => {
                      set("key", e.target.value);
                      setKeyTouched(true);
                    }}
                  />
                </Field>
                <Field id="cfg-description" label="Description" className="sm:col-span-2">
                  <Textarea id="cfg-description" rows={2} value={state.description} onChange={(e) => set("description", e.target.value)} />
                </Field>
                <label className="flex items-center justify-between gap-2 text-[13px] sm:col-span-2">
                  <span>
                    Configuration par défaut
                    <span className="block text-xs text-muted-foreground">Utilisée par les runs et benchmarks sans configuration explicite.</span>
                  </span>
                  <Switch checked={state.is_default} onCheckedChange={(c) => set("is_default", c)} />
                </label>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Pondération des dimensions</CardTitle>
                <CardDescription>Déplacer un curseur rééquilibre les autres proportionnellement : le total reste à 100 %.</CardDescription>
              </CardHeader>
              <CardContent>
                <WeightsEditor value={state.weights} onChange={(w) => set("weights", w)} initial={initialWeights} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Garde-fous</CardTitle>
                <CardDescription>Règles d&apos;invalidation ou de plafonnement appliquées après le composite.</CardDescription>
              </CardHeader>
              <CardContent>
                <GatesBuilder value={state.gates} onChange={(g) => set("gates", g)} meta={meta.data} showErrors={submitted} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Pondération des critères</CardTitle>
                <CardDescription>Poids d&apos;un critère dans la moyenne de sa dimension (défaut : poids du critère).</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-2">
                {state.criterionWeights.map((row, i) => (
                  <div key={i} className="grid grid-cols-[1fr_7rem_auto] items-center gap-2">
                    <SimpleSelect
                      size="sm"
                      aria-label="Critère"
                      value={row.key || undefined}
                      placeholder="Critère…"
                      options={(meta.data?.criteria ?? []).map((c) => ({ value: c.key, label: c.name, description: c.key }))}
                      onValueChange={(v) => set("criterionWeights", state.criterionWeights.map((r, j) => (j === i ? { ...r, key: v } : r)))}
                    />
                    <Input
                      size="sm"
                      type="number"
                      min={0}
                      step={0.1}
                      aria-label="Poids"
                      value={row.weight}
                      onChange={(e) => set("criterionWeights", state.criterionWeights.map((r, j) => (j === i ? { ...r, weight: e.target.value } : r)))}
                    />
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Retirer"
                      onClick={() => set("criterionWeights", state.criterionWeights.filter((_, j) => j !== i))}
                    >
                      <Trash2 aria-hidden />
                    </Button>
                  </div>
                ))}
                {submitted && errors.criterionWeights ? <p className="text-xs text-destructive">{errors.criterionWeights}</p> : null}
                <div>
                  <Button
                    variant="secondary"
                    size="sm"
                    leftIcon={<Plus aria-hidden />}
                    onClick={() => set("criterionWeights", [...state.criterionWeights, { key: "", weight: "1" }])}
                  >
                    Ajouter un poids de critère
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid content-start gap-4">
            <Card>
              <CardHeader>
                <CardTitle>Réussite</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4">
                <Field id="cfg-threshold" label="Seuil de réussite (0–100)" error={submitted ? errors.threshold : undefined} hint="Réussi = aucun garde-fou en échec et composite ≥ seuil.">
                  <Input id="cfg-threshold" type="number" min={0} max={100} value={state.passThreshold} onChange={(e) => set("passThreshold", e.target.value)} />
                </Field>
                <label className="flex items-center justify-between gap-2 text-[13px]">
                  <span>
                    Préférer les scores humains
                    <span className="block text-xs text-muted-foreground">Un score humain remplace le score IA dans le composite.</span>
                  </span>
                  <Switch checked={state.useHuman} onCheckedChange={(c) => set("useHuman", c)} />
                </label>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Juges épinglés</CardTitle>
                <CardDescription>Versions exactes de juges appelées pour chaque run.</CardDescription>
              </CardHeader>
              <CardContent>
                <JudgesPicker value={state.judgeIds} onChange={(v) => set("judgeIds", v)} pinned={pinnedJudges} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Agrégation multi-juges</CardTitle>
                <CardDescription>Combinaison des verdicts normalisés de chaque juge, par critère.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3">
                <SimpleSelect
                  aria-label="Méthode d'agrégation"
                  value={state.method}
                  onValueChange={(v) => set("method", v)}
                  options={AGGREGATION_METHODS.map((m) => ({ value: m, label: AGGREGATION_METHOD_META[m].label, description: AGGREGATION_METHOD_META[m].description }))}
                />
                {state.method === "weighted" ? (
                  <div className="grid gap-2">
                    <p className="text-xs text-muted-foreground">Poids par clé de juge (vide = poids du juge).</p>
                    {Array.from(new Set([...judgeKeys, ...Object.keys(state.aggWeights)])).map((k) => (
                      <div key={k} className="grid grid-cols-[1fr_6rem] items-center gap-2">
                        <span className="font-mono text-xs">{k}</span>
                        <Input
                          size="sm"
                          type="number"
                          min={0}
                          step={0.1}
                          aria-label={`Poids ${k}`}
                          value={state.aggWeights[k] ?? ""}
                          onChange={(e) => set("aggWeights", { ...state.aggWeights, [k]: e.target.value })}
                        />
                      </div>
                    ))}
                    <Input
                      size="sm"
                      placeholder="Ajouter une clé de juge puis Entrée"
                      aria-label="Ajouter une clé de juge"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          const k = e.currentTarget.value.trim();
                          if (k) set("aggWeights", { ...state.aggWeights, [k]: "1" });
                          e.currentTarget.value = "";
                        }
                      }}
                    />
                  </div>
                ) : null}
                {state.method === "custom" ? (
                  <Field id="cfg-expression" label="Expression" error={submitted ? errors.expression : fieldErrors["aggregation.expression"]} hint={AGGREGATION_HELP}>
                    <Textarea
                      id="cfg-expression"
                      rows={3}
                      className="font-mono text-[12.5px]"
                      value={state.expression}
                      onChange={(e) => set("expression", e.target.value)}
                      placeholder="min(scores) if max(scores) - min(scores) > 0.4 else mean(scores)"
                    />
                  </Field>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Normalisation</CardTitle>
                <CardDescription>Vide = valeur par défaut de FORGE.</CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-3">
                {NORMALIZATION_FIELDS.map((f) => (
                  <Field key={f.key} id={`cfg-norm-${f.key}`} label={f.label} hint={f.hint}>
                    <Input
                      id={`cfg-norm-${f.key}`}
                      type="number"
                      min={0}
                      step={f.step}
                      value={state.normalization[f.key] ?? ""}
                      onChange={(e) => set("normalization", { ...state.normalization, [f.key]: e.target.value })}
                    />
                  </Field>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Critères jugés sur tous les scénarios</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="grid max-h-64 gap-0.5 overflow-y-auto">
                  {judgedCriteria.map((c) => {
                    const checked = state.criteria.includes(c.key);
                    return (
                      <li key={c.key}>
                        <label className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-[13px] hover:bg-muted/60">
                          <Checkbox checked={checked} onCheckedChange={() => set("criteria", checked ? state.criteria.filter((k) => k !== c.key) : [...state.criteria, c.key])} />
                          <DimensionDot dimension={c.dimension} />
                          <span className="truncate">{c.name}</span>
                          <span className="ml-auto font-mono text-[11px] text-muted-foreground">{c.key}</span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Règles globales</CardTitle>
                <CardDescription>
                  Tableau JSON de règles (même format que les règles de scénario : id, type, params…).{" "}
                  <Link href="/scenarios" className="text-primary hover:underline">
                    Types de règles
                  </Link>
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Field id="cfg-rules" error={submitted ? errors.rules : rules.error ? rules.error : undefined}>
                  <Textarea id="cfg-rules" rows={8} className="font-mono text-[12.5px]" value={state.rulesJson} onChange={(e) => set("rulesJson", e.target.value)} />
                </Field>
              </CardContent>
            </Card>
          </div>
        </div>

        {mutation.error ? <Alert tone="red">{errorMessage(mutation.error)}</Alert> : null}
        {submitted && !valid ? <Alert tone="amber">Corrigez les champs signalés avant d&apos;enregistrer.</Alert> : null}
        <div className="flex flex-wrap justify-end gap-2">
          <Button asChild variant="secondary">
            <Link href={configId ? `/evaluation-configs/${configId}` : "/evaluation-configs"}>Annuler</Link>
          </Button>
          <Button type="submit" loading={mutation.isPending} leftIcon={<Save aria-hidden />}>
            {configId ? "Créer la version" : "Créer la configuration"}
          </Button>
        </div>
      </form>

      {previewConfigId && behaviour ? (
        <PreviewPanel
          className="mt-6"
          configId={previewConfigId}
          overrides={behaviour}
          title="Aperçu des modifications"
          description="Composites recalculés avec le formulaire actuel (non enregistré), à partir des verdicts déjà stockés : comparez avant / après et les changements de rang."
        />
      ) : null}
    </>
  );
}
