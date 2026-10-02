"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  BookOpen,
  Braces,
  FileText,
  ListChecks,
  ListPlus,
  MessageSquare,
  Plus,
  Ruler,
  Save,
  Scale,
  ShieldCheck,
  Tags,
  Target,
  Trash2,
  Wrench,
} from "lucide-react";

import { errorsUnder, fieldError, normalizeFieldPath } from "@/components/agents/kit/field-errors";
import { JsonField } from "@/components/agents/kit/json-field";
import { TagInput } from "@/components/agents/kit/tag-input";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCurrentUser } from "@/hooks/use-current-user";
import { isApiError } from "@/lib/api/client";
import type { ApiFieldError } from "@/lib/api/types";
import { useCreateScenario, useCreateScenarioVersion, useMeta, type Meta, type ScenarioDetail } from "@/lib/api/scenarios";
import {
  CLASSIFICATION_META,
  CLASSIFICATIONS,
  DIFFICULTIES,
  DIFFICULTY_META,
  SCENARIO_VISIBILITIES,
  SCENARIO_VISIBILITY_META,
  type Difficulty,
  type ScenarioVisibility,
} from "@/lib/enums";
import { plural } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  buildContent,
  emptyContent,
  toggleSectionMode,
  uid,
  type ContentState,
  type CriterionRow,
  type DocumentRow,
  type MockRow,
} from "./editor-model";
import { RuleBuilder } from "./rule-builder";

const OTHER = "__other__";

export interface ScenarioMetaState {
  name: string;
  slug: string;
  category: string;
  visibility: ScenarioVisibility;
  classification: number;
  tags: string[];
  fresh_until: string;
}

export interface ScenarioEditorProps {
  mode: "create" | "version";
  /** Version mode: the scenario receiving the new version. */
  scenario?: ScenarioDetail;
  /** Prefilled content (latest version, or a version to start from). */
  initialContent?: ContentState;
  /** Label of the version the content comes from ("v3"). */
  basedOn?: string;
}

function Section({
  icon,
  title,
  description,
  children,
  aside,
  invalid,
}: {
  icon: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  aside?: React.ReactNode;
  invalid?: boolean;
}) {
  return (
    <Card className={cn(invalid && "border-destructive/60")}>
      <CardHeader className="flex-row flex-wrap items-start gap-3">
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

function ModeSwitch({ value, onToggle, label }: { value: "form" | "json"; onToggle: () => void; label: string }) {
  return (
    <SegmentedControl
      size="sm"
      aria-label={`Mode d'édition : ${label}`}
      value={value}
      onValueChange={(v) => v !== value && onToggle()}
      options={[
        { value: "form", label: "Formulaire" },
        { value: "json", label: "JSON avancé", icon: <Braces aria-hidden /> },
      ]}
    />
  );
}

/** Scenario editor: metadata (creation) + structured content with "JSON avancé" modes. */
export function ScenarioEditor({ mode, scenario, initialContent, basedOn }: ScenarioEditorProps) {
  const router = useRouter();
  const meta = useMeta();
  const { hasRole, clearance } = useCurrentUser();
  const isMaintainer = hasRole("maintainer");
  const [metaState, setMetaState] = React.useState<ScenarioMetaState>({
    name: "",
    slug: "",
    category: "",
    visibility: "public",
    classification: 1,
    tags: [],
    fresh_until: "",
  });
  const [customCategory, setCustomCategory] = React.useState(false);
  const [content, setContent] = React.useState<ContentState>(() => initialContent ?? emptyContent());
  const [changelog, setChangelog] = React.useState(mode === "create" ? "Version initiale" : "");
  const [localError, setLocalError] = React.useState<string | null>(null);
  const create = useCreateScenario();
  const createVersion = useCreateScenarioVersion(scenario?.id ?? "");
  const mutation = mode === "create" ? create : createVersion;
  const error = mutation.error;
  const errors: ReadonlyArray<ApiFieldError> = isApiError(error) ? error.errors : [];
  const fe = (path: string, deep = false) => fieldError(errors, path, { deep });
  const sectionInvalid = (path: string) => errorsUnder(errors, path).length > 0;

  const set = <K extends keyof ContentState>(key: K, value: ContentState[K]) => setContent((s) => ({ ...s, [key]: value }));
  const setMeta = <K extends keyof ScenarioMetaState>(key: K, value: ScenarioMetaState[K]) => setMetaState((s) => ({ ...s, [key]: value }));

  const toggle = (section: "criteria" | "rules" | "mocks") => {
    const result = toggleSectionMode(content, section);
    if ("error" in result) {
      toast.error(result.error);
      return;
    }
    setContent(result.next);
  };

  const built = buildContent(content);
  const categories = meta.data?.categories ?? [];
  const isKnownCategory = categories.some((c) => c.value === metaState.category);
  const canSubmit =
    !mutation.isPending &&
    built.invalid.length === 0 &&
    (mode === "version" || (metaState.name.trim().length > 0 && metaState.category.trim().length > 0));
  const sensitiveLevel = mode === "create" ? metaState.classification : (scenario?.classification ?? 0);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    if (built.invalid.length) {
      setLocalError(`JSON invalide : ${built.invalid.join(", ")}`);
      return;
    }
    if (!canSubmit) return;
    const onError = () => window.scrollTo({ top: 0, behavior: "smooth" });
    if (mode === "create") {
      create.mutate(
        {
          name: metaState.name.trim(),
          slug: metaState.slug.trim() || null,
          category: metaState.category.trim(),
          visibility: metaState.visibility,
          classification: metaState.classification,
          tags: metaState.tags,
          fresh_until: metaState.visibility === "fresh" && metaState.fresh_until ? `${metaState.fresh_until}T23:59:59Z` : null,
          changelog: changelog.trim(),
          content: built.content,
        },
        {
          onSuccess: (s) => {
            toast.success("Scénario créé", { description: `${s.name} · v${s.latest_version}` });
            router.push(`/scenarios/${s.id}`);
          },
          onError,
        },
      );
    } else if (scenario) {
      createVersion.mutate(
        { content: built.content, changelog: changelog.trim() },
        {
          onSuccess: (v) => {
            toast.success(`Version ${v.version} créée`);
            router.push(`/scenarios/${scenario.id}?tab=versions&version=${v.id}`);
          },
          onError,
        },
      );
    }
  };

  return (
    <form onSubmit={submit} className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]" noValidate>
      <div className="grid min-w-0 content-start gap-4">
        <ClassificationBanner level={sensitiveLevel} context="scenario" />
        {error ? (
          error.isConflict ? (
            <Alert tone="amber" title="Contenu identique">
              {error.detail}
            </Alert>
          ) : (
            <Alert tone="red" title={errors.length ? `Scénario invalide (${plural(errors.length, "erreur")})` : "Enregistrement impossible"}>
              {errors.length ? (
                <ul className="list-disc pl-4">
                  {errors.map((er, i) => (
                    <li key={i}>
                      <span className="font-mono text-[12px]">{normalizeFieldPath(er.field)}</span> : {er.message}
                    </li>
                  ))}
                </ul>
              ) : (
                error.detail
              )}
            </Alert>
          )
        ) : null}
        {localError ? <Alert tone="red">{localError}</Alert> : null}

        {mode === "create" ? (
          <Section icon={<Tags />} title="Métadonnées" description="Modifiables plus tard sans créer de version (sauf le contenu).">
            <div className="grid gap-4 md:grid-cols-2">
              <Field id="sc-name" label="Nom" required error={fe("name")}>
                <Input
                  id="sc-name"
                  value={metaState.name}
                  onChange={(e) => setMeta("name", e.target.value)}
                  maxLength={300}
                  invalid={Boolean(fe("name"))}
                />
              </Field>
              <Field id="sc-slug" label="Identifiant (slug)" hint="Vide : généré depuis la catégorie (ex. scenario_pm_004)." error={fe("slug")}>
                <Input
                  id="sc-slug"
                  value={metaState.slug}
                  onChange={(e) => setMeta("slug", e.target.value)}
                  placeholder="Généré depuis la catégorie"
                  maxLength={120}
                  className="font-mono"
                  invalid={Boolean(fe("slug"))}
                />
              </Field>
              <Field id="sc-category" label="Catégorie" required error={fe("category")} hint="Liste suggérée ou texte libre.">
                {customCategory || (metaState.category && !isKnownCategory) ? (
                  <div className="flex gap-2">
                    <Input id="sc-category" value={metaState.category} onChange={(e) => setMeta("category", e.target.value)} maxLength={100} />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setCustomCategory(false);
                        setMeta("category", "");
                      }}
                    >
                      Liste
                    </Button>
                  </div>
                ) : (
                  <SimpleSelect
                    id="sc-category"
                    value={metaState.category || undefined}
                    onValueChange={(v) => {
                      if (v === OTHER) {
                        setCustomCategory(true);
                        setMeta("category", "");
                      } else setMeta("category", v);
                    }}
                    placeholder="Choisir une catégorie…"
                    options={[...categories.map((c) => ({ value: c.value, label: c.label })), { value: OTHER, label: "Autre (texte libre)…" }]}
                  />
                )}
              </Field>
              <Field id="sc-visibility" label="Visibilité" error={fe("visibility")} hint={SCENARIO_VISIBILITY_META[metaState.visibility].description}>
                <SimpleSelect<ScenarioVisibility>
                  id="sc-visibility"
                  value={metaState.visibility}
                  onValueChange={(v) => setMeta("visibility", v)}
                  options={SCENARIO_VISIBILITIES.map((v) => ({
                    value: v,
                    label: SCENARIO_VISIBILITY_META[v].label,
                    disabled: v === "private" && !isMaintainer,
                    description: v === "private" && !isMaintainer ? "Réservé aux mainteneurs" : undefined,
                  }))}
                />
              </Field>
              <Field id="sc-classification" label="Classification" error={fe("classification")} hint="Les niveaux au-delà de votre habilitation ne sont pas proposés.">
                <SimpleSelect
                  id="sc-classification"
                  value={String(metaState.classification)}
                  onValueChange={(v) => setMeta("classification", Number(v))}
                  options={CLASSIFICATIONS.map((c) => ({
                    value: String(c),
                    label: `${CLASSIFICATION_META[c].code} — ${CLASSIFICATION_META[c].label}`,
                    description: CLASSIFICATION_META[c].description,
                    disabled: c > clearance,
                  }))}
                />
              </Field>
              {metaState.visibility === "fresh" ? (
                <Field id="sc-fresh" label="Fresh jusqu'au" hint="Défaut : 30 jours après la création." error={fe("fresh_until")}>
                  <Input id="sc-fresh" type="date" value={metaState.fresh_until} onChange={(e) => setMeta("fresh_until", e.target.value)} />
                </Field>
              ) : null}
              <Field id="sc-tags" label="Étiquettes" error={fe("tags", true)} className="md:col-span-2">
                <TagInput id="sc-tags" value={metaState.tags} onChange={(v) => setMeta("tags", v)} />
              </Field>
            </div>
          </Section>
        ) : null}

        <Section icon={<FileText />} title="Description & difficulté" invalid={sectionInvalid("description") || sectionInvalid("difficulty")}>
          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_14rem]">
            <Field id="sc-description" label="Description (Markdown)" hint="Non transmise à l'agent." error={fe("description")}>
              <Textarea id="sc-description" value={content.description} onChange={(e) => set("description", e.target.value)} rows={4} />
            </Field>
            <Field id="sc-difficulty" label="Difficulté" error={fe("difficulty")}>
              <SimpleSelect<Difficulty>
                id="sc-difficulty"
                value={content.difficulty}
                onValueChange={(v) => set("difficulty", v)}
                options={DIFFICULTIES.map((d) => ({ value: d, label: DIFFICULTY_META[d].label }))}
              />
            </Field>
          </div>
        </Section>

        <InputSection content={content} set={set} errors={errors} />
        <DocumentsSection documents={content.documents} onChange={(d) => set("documents", d)} errors={errors} />
        <ConstraintsSection constraints={content.constraints} onChange={(c) => set("constraints", c)} errors={errors} />

        <Section
          icon={<Target />}
          title="Résultat attendu"
          description="Référence pour les juges, jamais transmise à l'agent."
          invalid={sectionInvalid("expected_output")}
          aside={
            <SegmentedControl
              size="sm"
              aria-label="Format du résultat attendu"
              value={content.expectedMode}
              onValueChange={(v) => set("expectedMode", v)}
              options={[
                { value: "text", label: "Texte (Markdown)" },
                { value: "json", label: "JSON" },
              ]}
            />
          }
        >
          {content.expectedMode === "text" ? (
            <Field id="sc-expected" error={fe("expected_output", true)}>
              <Textarea id="sc-expected" value={content.expectedText} onChange={(e) => set("expectedText", e.target.value)} rows={8} className="font-mono text-[12.5px]" />
            </Field>
          ) : (
            <JsonField id="sc-expected-json" value={content.expectedJson} onChange={(v) => set("expectedJson", v)} rows={8} error={fe("expected_output", true)} />
          )}
        </Section>

        <Section icon={<ShieldCheck />} title="Comportement attendu" invalid={sectionInvalid("expected_behavior")}>
          <Field id="sc-behavior" hint="Ex. « Refuse poliment toute demande de données personnelles. »" error={fe("expected_behavior")}>
            <Textarea id="sc-behavior" value={content.expectedBehavior} onChange={(e) => set("expectedBehavior", e.target.value)} rows={3} />
          </Field>
        </Section>

        <Section
          icon={<Scale />}
          title="Critères"
          description="Critères jugés sur ce scénario (vide : critères par défaut de la configuration)."
          invalid={sectionInvalid("criteria")}
          aside={<ModeSwitch value={content.criteriaMode} onToggle={() => toggle("criteria")} label="critères" />}
        >
          {content.criteriaMode === "json" ? (
            <JsonField
              id="sc-criteria-json"
              value={content.criteriaJson}
              onChange={(v) => set("criteriaJson", v)}
              expect="array"
              rows={10}
              error={fe("criteria", true)}
              hint='[{"key": "quality.completeness", "weight": 2, "question": "…"}]'
            />
          ) : (
            <CriteriaEditor rows={content.criteria} onChange={(c) => set("criteria", c)} meta={meta.data} errors={errors} />
          )}
        </Section>

        <Section
          icon={<Ruler />}
          title="Règles déterministes"
          description="Évaluées sans juge, gratuitement ; un échec produit une erreur typée."
          invalid={sectionInvalid("rules")}
          aside={<ModeSwitch value={content.rulesMode} onToggle={() => toggle("rules")} label="règles" />}
        >
          {content.rulesMode === "json" ? (
            <JsonField
              id="sc-rules-json"
              value={content.rulesJson}
              onChange={(v) => set("rulesJson", v)}
              expect="array"
              rows={14}
              error={fe("rules", true)}
              hint='[{"id": "R1", "type": "sections_present", "params": {"sections": ["Objectifs"]}, "severity": "medium"}]'
            />
          ) : (
            <RuleBuilder rules={content.rules} onChange={(r) => set("rules", r)} meta={meta.data} errors={errors} canHide={isMaintainer} />
          )}
        </Section>

        <Section
          icon={<Wrench />}
          title="Mocks d'outils"
          description="Réponses déterministes aux appels d'outils (première correspondance gagnante)."
          invalid={sectionInvalid("tool_mocks")}
          aside={<ModeSwitch value={content.mocksMode} onToggle={() => toggle("mocks")} label="mocks" />}
        >
          {content.mocksMode === "json" ? (
            <JsonField
              id="sc-mocks-json"
              value={content.mocksJson}
              onChange={(v) => set("mocksJson", v)}
              expect="array"
              rows={10}
              error={fe("tool_mocks", true)}
              hint='[{"tool": "search_docs", "match": {"query": "export"}, "response": {"results": []}}]'
            />
          ) : (
            <MocksEditor rows={content.mocks} onChange={(m) => set("mocks", m)} errors={errors} />
          )}
        </Section>
      </div>

      <aside className="grid content-start gap-4 xl:sticky xl:top-20 xl:self-start">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Save className="size-4 text-muted-foreground" aria-hidden />
              {mode === "create" ? "Créer le scénario" : "Nouvelle version"}
            </CardTitle>
            <CardDescription>
              {mode === "create"
                ? "La version 1 est créée avec un canari unique."
                : `Contenu immuable : une nouvelle version${basedOn ? ` (à partir de ${basedOn})` : ""} est créée avec son empreinte.`}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <Field id="sc-changelog" label="Journal des modifications" error={fe("changelog")}>
              <Textarea id="sc-changelog" value={changelog} onChange={(e) => setChangelog(e.target.value)} rows={3} maxLength={10000} />
            </Field>
            <dl className="grid grid-cols-2 gap-2 text-xs">
              {[
                ["Documents", content.documents.length],
                ["Contraintes", content.constraints.length],
                ["Critères", content.criteriaMode === "form" ? content.criteria.length : "JSON"],
                ["Règles", content.rulesMode === "form" ? content.rules.length : "JSON"],
                ["Mocks", content.mocksMode === "form" ? content.mocks.length : "JSON"],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded-md border border-border bg-muted/30 px-2 py-1.5">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="font-semibold tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
            {built.invalid.length ? (
              <p role="alert" className="text-xs font-medium text-destructive">
                JSON invalide : {built.invalid.join(", ")}
              </p>
            ) : null}
            <Button type="submit" loading={mutation.isPending} disabled={!canSubmit} leftIcon={<Save aria-hidden />}>
              {mode === "create" ? "Créer le scénario" : "Créer la version"}
            </Button>
            <Button asChild variant="ghost">
              <Link href={scenario ? `/scenarios/${scenario.id}` : "/scenarios"}>Annuler</Link>
            </Button>
          </CardContent>
        </Card>
      </aside>
    </form>
  );
}

function InputSection({
  content,
  set,
  errors,
}: {
  content: ContentState;
  set: <K extends keyof ContentState>(key: K, value: ContentState[K]) => void;
  errors: ReadonlyArray<ApiFieldError>;
}) {
  const fe = (path: string) => fieldError(errors, path, { deep: true });
  return (
    <Section
      icon={<MessageSquare />}
      title="Entrée de l'agent"
      description="Prompt unique ou conversation ; les champs supplémentaires sont conservés."
      invalid={errorsUnder(errors, "input").length > 0}
      aside={
        <SegmentedControl
          size="sm"
          aria-label="Format de l'entrée"
          value={content.inputMode}
          onValueChange={(v) => set("inputMode", v)}
          options={[
            { value: "prompt", label: "Prompt" },
            { value: "messages", label: "Messages" },
            { value: "json", label: "JSON" },
          ]}
        />
      }
    >
      {content.inputMode === "prompt" ? (
        <Field id="sc-prompt" label="Prompt" required error={fe("input")}>
          <Textarea id="sc-prompt" value={content.prompt} onChange={(e) => set("prompt", e.target.value)} rows={6} invalid={Boolean(fe("input"))} />
        </Field>
      ) : content.inputMode === "messages" ? (
        <div className="grid gap-2">
          {content.messages.map((m, i) => (
            <div key={m.uid} className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-[9rem_minmax(0,1fr)_auto]">
              <SimpleSelect
                aria-label={`Rôle du message ${i + 1}`}
                size="sm"
                value={m.role}
                onValueChange={(role) => set("messages", content.messages.map((x) => (x.uid === m.uid ? { ...x, role } : x)))}
                options={[
                  { value: "system", label: "system" },
                  { value: "user", label: "user" },
                  { value: "assistant", label: "assistant" },
                ]}
              />
              <Textarea
                aria-label={`Contenu du message ${i + 1}`}
                value={m.content}
                onChange={(e) => set("messages", content.messages.map((x) => (x.uid === m.uid ? { ...x, content: e.target.value } : x)))}
                rows={3}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                onClick={() => set("messages", content.messages.filter((x) => x.uid !== m.uid))}
                aria-label={`Supprimer le message ${i + 1}`}
              >
                <Trash2 aria-hidden />
              </Button>
            </div>
          ))}
          {fe("input") ? (
            <p role="alert" className="text-xs font-medium text-destructive">
              {fe("input")}
            </p>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="w-fit"
            leftIcon={<Plus aria-hidden />}
            onClick={() => set("messages", [...content.messages, { uid: uid(), role: content.messages.length % 2 ? "assistant" : "user", content: "" }])}
          >
            Ajouter un message
          </Button>
        </div>
      ) : (
        <JsonField
          id="sc-input-json"
          value={content.inputJson}
          onChange={(v) => set("inputJson", v)}
          expect="object"
          rows={8}
          error={fe("input")}
          hint='{"prompt": "…"} ou {"messages": [{"role": "user", "content": "…"}]}'
        />
      )}
      {content.inputMode !== "json" && Object.keys(content.inputRest).length ? (
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          Champs conservés :
          {Object.keys(content.inputRest).map((k) => (
            <Badge key={k} mono>
              {k}
            </Badge>
          ))}
        </p>
      ) : null}
    </Section>
  );
}

function DocumentsSection({
  documents,
  onChange,
  errors,
}: {
  documents: DocumentRow[];
  onChange: (d: DocumentRow[]) => void;
  errors: ReadonlyArray<ApiFieldError>;
}) {
  const update = (u: string, patch: Partial<DocumentRow>) => onChange(documents.map((d) => (d.uid === u ? { ...d, ...patch } : d)));
  return (
    <Section
      icon={<BookOpen />}
      title="Contexte : documents"
      description="Documents fournis à l'agent (citables par leur identifiant ou leur titre)."
      invalid={errorsUnder(errors, "context").length > 0}
    >
      {documents.length === 0 ? <p className="text-[13px] text-subtle-foreground">Aucun document.</p> : null}
      {documents.map((d, i) => {
        const prefix = `context.documents[${i}]`;
        return (
          <div key={d.uid} className="grid gap-3 rounded-lg border border-border p-3 md:grid-cols-[10rem_minmax(0,1fr)_10rem_auto]">
            <Field id={`doc-${d.uid}-id`} label="Identifiant" error={fieldError(errors, `${prefix}.id`)}>
              <Input id={`doc-${d.uid}-id`} size="sm" value={d.id} onChange={(e) => update(d.uid, { id: e.target.value })} className="font-mono" />
            </Field>
            <Field id={`doc-${d.uid}-title`} label="Titre" error={fieldError(errors, `${prefix}.title`)}>
              <Input id={`doc-${d.uid}-title`} size="sm" value={d.title} onChange={(e) => update(d.uid, { title: e.target.value })} />
            </Field>
            <Field id={`doc-${d.uid}-source`} label="Source" error={fieldError(errors, `${prefix}.source`)}>
              <Input id={`doc-${d.uid}-source`} size="sm" value={d.source} onChange={(e) => update(d.uid, { source: e.target.value })} />
            </Field>
            <div className="flex items-end pb-0.5">
              <Button type="button" variant="ghost" size="icon-sm" onClick={() => onChange(documents.filter((x) => x.uid !== d.uid))} aria-label={`Supprimer le document ${d.id || i + 1}`}>
                <Trash2 aria-hidden />
              </Button>
            </div>
            <Field id={`doc-${d.uid}-content`} label="Contenu" error={fieldError(errors, `${prefix}.content`)} className="md:col-span-4">
              <Textarea id={`doc-${d.uid}-content`} value={d.content} onChange={(e) => update(d.uid, { content: e.target.value })} rows={4} />
            </Field>
          </div>
        );
      })}
      {fieldError(errors, "context") ? (
        <p role="alert" className="text-xs font-medium text-destructive">
          {fieldError(errors, "context")}
        </p>
      ) : null}
      <Button
        type="button"
        variant="secondary"
        size="sm"
        className="w-fit"
        leftIcon={<ListPlus aria-hidden />}
        onClick={() => onChange([...documents, { uid: uid(), id: `doc-${documents.length + 1}`, title: "", content: "", source: "", extra: {} }])}
      >
        Ajouter un document
      </Button>
    </Section>
  );
}

function ConstraintsSection({
  constraints,
  onChange,
  errors,
}: {
  constraints: string[];
  onChange: (c: string[]) => void;
  errors: ReadonlyArray<ApiFieldError>;
}) {
  const [draft, setDraft] = React.useState("");
  const add = () => {
    if (!draft.trim()) return;
    onChange([...constraints, draft.trim()]);
    setDraft("");
  };
  return (
    <Section icon={<ListChecks />} title="Contraintes" description="Consignes explicites transmises à l'agent." invalid={errorsUnder(errors, "constraints").length > 0}>
      {constraints.length ? (
        <ol className="grid gap-2">
          {constraints.map((c, i) => (
            <li key={i} className="flex items-center gap-2">
              <span className="w-5 shrink-0 text-right text-xs tabular-nums text-muted-foreground">{i + 1}.</span>
              <Input
                size="sm"
                value={c}
                aria-label={`Contrainte ${i + 1}`}
                onChange={(e) => onChange(constraints.map((x, j) => (j === i ? e.target.value : x)))}
                invalid={Boolean(fieldError(errors, `constraints[${i}]`))}
              />
              <Button type="button" variant="ghost" size="icon-sm" onClick={() => onChange(constraints.filter((_, j) => j !== i))} aria-label={`Supprimer la contrainte ${i + 1}`}>
                <Trash2 aria-hidden />
              </Button>
            </li>
          ))}
        </ol>
      ) : null}
      <div className="flex gap-2">
        <Input
          size="sm"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder="Ex. Citer les sources utilisées"
          aria-label="Nouvelle contrainte"
        />
        <Button type="button" variant="secondary" size="sm" onClick={add} disabled={!draft.trim()} leftIcon={<Plus aria-hidden />}>
          Ajouter
        </Button>
      </div>
      {fieldError(errors, "constraints", { deep: true }) ? (
        <p role="alert" className="text-xs font-medium text-destructive">
          {fieldError(errors, "constraints", { deep: true })}
        </p>
      ) : null}
    </Section>
  );
}

function CriteriaEditor({
  rows,
  onChange,
  meta,
  errors,
}: {
  rows: CriterionRow[];
  onChange: (r: CriterionRow[]) => void;
  meta: Meta | undefined;
  errors: ReadonlyArray<ApiFieldError>;
}) {
  const update = (u: string, patch: Partial<CriterionRow>) => onChange(rows.map((r) => (r.uid === u ? { ...r, ...patch } : r)));
  const catalog = meta?.criteria ?? [];
  const used = new Set(rows.map((r) => r.key));
  return (
    <div className="grid gap-2">
      {rows.length === 0 ? <p className="text-[13px] text-subtle-foreground">Aucun critère spécifique.</p> : null}
      {rows.map((c, i) => {
        const prefix = `criteria[${i}]`;
        const known = catalog.find((x) => x.key === c.key);
        return (
          <div key={c.uid} className={cn("grid gap-3 rounded-lg border p-3 md:grid-cols-[minmax(0,1fr)_6rem_auto]", errorsUnder(errors, prefix).length ? "border-destructive/60" : "border-border")}>
            <Field id={`crit-${c.uid}`} label="Critère" error={fieldError(errors, `${prefix}.key`) ?? fieldError(errors, prefix)} hint={known?.question}>
              <SimpleSelect
                id={`crit-${c.uid}`}
                size="sm"
                value={c.key || undefined}
                onValueChange={(key) => update(c.uid, { key })}
                placeholder="Choisir un critère…"
                options={[
                  ...catalog.map((x) => ({ value: x.key, label: x.name, description: x.key, disabled: used.has(x.key) && x.key !== c.key })),
                  ...(c.key && !known ? [{ value: c.key, label: c.key, description: "Hors catalogue", disabled: false }] : []),
                ]}
              />
            </Field>
            <Field id={`crit-${c.uid}-w`} label="Poids" error={fieldError(errors, `${prefix}.weight`)}>
              <Input id={`crit-${c.uid}-w`} size="sm" inputMode="decimal" value={c.weight} placeholder="1" onChange={(e) => update(c.uid, { weight: e.target.value })} />
            </Field>
            <div className="flex items-end pb-0.5">
              <Button type="button" variant="ghost" size="icon-sm" onClick={() => onChange(rows.filter((x) => x.uid !== c.uid))} aria-label={`Supprimer le critère ${c.key || i + 1}`}>
                <Trash2 aria-hidden />
              </Button>
            </div>
            <Field id={`crit-${c.uid}-q`} label="Question spécifique (optionnelle)" className="md:col-span-3" error={fieldError(errors, `${prefix}.question`)}>
              <Input id={`crit-${c.uid}-q`} size="sm" value={c.question} onChange={(e) => update(c.uid, { question: e.target.value })} />
            </Field>
          </div>
        );
      })}
      <Button
        type="button"
        variant="secondary"
        size="sm"
        className="w-fit"
        leftIcon={<Plus aria-hidden />}
        onClick={() => onChange([...rows, { uid: uid(), key: "", weight: "", question: "", rubric: "", extra: {} }])}
      >
        Ajouter un critère
      </Button>
    </div>
  );
}

function MocksEditor({ rows, onChange, errors }: { rows: MockRow[]; onChange: (r: MockRow[]) => void; errors: ReadonlyArray<ApiFieldError> }) {
  const update = (u: string, patch: Partial<MockRow>) => onChange(rows.map((r) => (r.uid === u ? { ...r, ...patch } : r)));
  return (
    <div className="grid gap-3">
      {rows.length === 0 ? <p className="text-[13px] text-subtle-foreground">Aucun mock d&apos;outil.</p> : null}
      {rows.map((m, i) => {
        const prefix = `tool_mocks[${i}]`;
        return (
          <div key={m.uid} className={cn("grid gap-3 rounded-lg border p-3 md:grid-cols-2", errorsUnder(errors, prefix).length ? "border-destructive/60" : "border-border")}>
            <div className="flex items-end gap-2 md:col-span-2">
              <Field id={`mock-${m.uid}-tool`} label="Outil" required error={fieldError(errors, `${prefix}.tool`) ?? fieldError(errors, prefix)} className="flex-1">
                <Input id={`mock-${m.uid}-tool`} size="sm" value={m.tool} onChange={(e) => update(m.uid, { tool: e.target.value })} className="font-mono" />
              </Field>
              <Field id={`mock-${m.uid}-lat`} label="Latence (ms)" className="w-32">
                <Input id={`mock-${m.uid}-lat`} size="sm" inputMode="numeric" value={m.latency_ms} onChange={(e) => update(m.uid, { latency_ms: e.target.value })} />
              </Field>
              <Button type="button" variant="ghost" size="icon-sm" onClick={() => onChange(rows.filter((x) => x.uid !== m.uid))} aria-label={`Supprimer le mock ${m.tool || i + 1}`}>
                <Trash2 aria-hidden />
              </Button>
            </div>
            <JsonField
              id={`mock-${m.uid}-match`}
              label="Correspondance (sous-ensemble des arguments)"
              hint="Vide : tout appel de l'outil."
              value={m.match}
              onChange={(v) => update(m.uid, { match: v })}
              expect="object"
              rows={4}
              error={fieldError(errors, `${prefix}.match`, { deep: true })}
            />
            <JsonField
              id={`mock-${m.uid}-response`}
              label="Réponse"
              hint="JSON (ou texte brut)."
              value={m.response}
              onChange={(v) => update(m.uid, { response: v })}
              rows={4}
              error={fieldError(errors, `${prefix}.response`, { deep: true })}
            />
            <Field id={`mock-${m.uid}-error`} label="Erreur simulée (optionnelle)" className="md:col-span-2" error={fieldError(errors, `${prefix}.error`)}>
              <Input id={`mock-${m.uid}-error`} size="sm" value={m.error} onChange={(e) => update(m.uid, { error: e.target.value })} placeholder="Service indisponible" />
            </Field>
          </div>
        );
      })}
      <Button
        type="button"
        variant="secondary"
        size="sm"
        className="w-fit"
        leftIcon={<Plus aria-hidden />}
        onClick={() => onChange([...rows, { uid: uid(), tool: "", match: "", response: "", error: "", latency_ms: "" }])}
      >
        Ajouter un mock
      </Button>
    </div>
  );
}
