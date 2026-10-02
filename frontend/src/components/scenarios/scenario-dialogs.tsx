"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { fieldError } from "@/components/agents/kit/field-errors";
import { JsonField, parseJsonText } from "@/components/agents/kit/json-field";
import { TagInput } from "@/components/agents/kit/tag-input";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCurrentUser } from "@/hooks/use-current-user";
import { isApiError } from "@/lib/api/client";
import { useCreateVariant, useMeta, useUpdateScenario, type ScenarioContentInput, type ScenarioDetail } from "@/lib/api/scenarios";
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

const KEEP = "__keep__";

function dateInput(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : "";
}

/** Edit non-behavioural scenario metadata (`PATCH /scenarios/{id}`). */
export function ScenarioMetaDialog({ open, onOpenChange, scenario }: { open: boolean; onOpenChange: (o: boolean) => void; scenario: ScenarioDetail }) {
  const meta = useMeta();
  const { hasRole, clearance } = useCurrentUser();
  const isMaintainer = hasRole("maintainer");
  const update = useUpdateScenario(scenario.id);
  const [name, setName] = React.useState(scenario.name);
  const [category, setCategory] = React.useState(scenario.category);
  const [tags, setTags] = React.useState<string[]>(scenario.tags);
  const [visibility, setVisibility] = React.useState<ScenarioVisibility>(scenario.visibility);
  const [classification, setClassification] = React.useState(scenario.classification);
  const [freshUntil, setFreshUntil] = React.useState(dateInput(scenario.fresh_until));
  const errors = isApiError(update.error) ? update.error.errors : [];

  React.useEffect(() => {
    if (open) {
      setName(scenario.name);
      setCategory(scenario.category);
      setTags(scenario.tags);
      setVisibility(scenario.visibility);
      setClassification(scenario.classification);
      setFreshUntil(dateInput(scenario.fresh_until));
      update.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, scenario]);

  const categories = meta.data?.categories ?? [];
  const categoryOptions = [
    ...categories.map((c) => ({ value: c.value, label: c.label })),
    ...(categories.some((c) => c.value === category) ? [] : [{ value: category, label: category }]),
  ];

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    update.mutate(
      {
        name: name.trim(),
        category: category.trim(),
        tags,
        visibility,
        classification,
        fresh_until: visibility === "fresh" && freshUntil ? `${freshUntil}T23:59:59Z` : null,
      },
      {
        onSuccess: () => {
          toast.success("Scénario mis à jour");
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !update.isPending && onOpenChange(o)}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Modifier les métadonnées</DialogTitle>
            <DialogDescription>Nom, catégorie, étiquettes, visibilité et classification. Le contenu se modifie en créant une nouvelle version.</DialogDescription>
          </DialogHeader>
          {update.error && !errors.length ? <Alert tone="red">{update.error.detail}</Alert> : null}
          <ClassificationBanner level={classification} context="scenario" compact />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="meta-name" label="Nom" required error={fieldError(errors, "name")} className="sm:col-span-2">
              <Input id="meta-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={300} required />
            </Field>
            <Field id="meta-category" label="Catégorie" error={fieldError(errors, "category")}>
              <SimpleSelect id="meta-category" value={category} onValueChange={setCategory} options={categoryOptions} />
            </Field>
            <Field
              id="meta-visibility"
              label="Visibilité"
              error={fieldError(errors, "visibility")}
              hint={!isMaintainer && (visibility === "private" || scenario.visibility === "private") ? "Les scénarios privés sont gérés par les mainteneurs." : SCENARIO_VISIBILITY_META[visibility].description}
            >
              <SimpleSelect<ScenarioVisibility>
                id="meta-visibility"
                value={visibility}
                onValueChange={setVisibility}
                disabled={!isMaintainer && scenario.visibility === "private"}
                options={SCENARIO_VISIBILITIES.map((v) => ({
                  value: v,
                  label: SCENARIO_VISIBILITY_META[v].label,
                  disabled: v === "private" && !isMaintainer,
                }))}
              />
            </Field>
            <Field id="meta-classification" label="Classification" error={fieldError(errors, "classification")}>
              <SimpleSelect
                id="meta-classification"
                value={String(classification)}
                onValueChange={(v) => setClassification(Number(v))}
                options={CLASSIFICATIONS.map((c) => ({
                  value: String(c),
                  label: `${CLASSIFICATION_META[c].code} — ${CLASSIFICATION_META[c].label}`,
                  disabled: c > clearance,
                }))}
              />
            </Field>
            {visibility === "fresh" ? (
              <Field id="meta-fresh" label="Fresh jusqu'au" error={fieldError(errors, "fresh_until")}>
                <Input id="meta-fresh" type="date" value={freshUntil} onChange={(e) => setFreshUntil(e.target.value)} />
              </Field>
            ) : null}
            <Field id="meta-tags" label="Étiquettes" className="sm:col-span-2" error={fieldError(errors, "tags", { deep: true })}>
              <TagInput id="meta-tags" value={tags} onChange={setTags} />
            </Field>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={update.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={update.isPending} disabled={!name.trim()}>
              Enregistrer
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Create a variant in the same family (`POST /scenarios/{id}/variants`) with content overrides. */
export function VariantDialog({ open, onOpenChange, scenario }: { open: boolean; onOpenChange: (o: boolean) => void; scenario: ScenarioDetail }) {
  const router = useRouter();
  const { hasRole } = useCurrentUser();
  const isMaintainer = hasRole("maintainer");
  const create = useCreateVariant(scenario.id);
  const latest = scenario.latest;
  const latestPrompt = latest?.input && typeof latest.input.prompt === "string" ? latest.input.prompt : "";
  const [label, setLabel] = React.useState("");
  const [name, setName] = React.useState("");
  const [visibility, setVisibility] = React.useState<string>(KEEP);
  const [tags, setTags] = React.useState<string[]>([]);
  const [difficulty, setDifficulty] = React.useState<string>(KEEP);
  const [prompt, setPrompt] = React.useState(latestPrompt);
  const [constraints, setConstraints] = React.useState<string[] | null>(null);
  const [advanced, setAdvanced] = React.useState("");
  const [changelog, setChangelog] = React.useState("");
  const errors = isApiError(create.error) ? create.error.errors : [];
  const adv = parseJsonText(advanced, {});
  const advValid = adv.ok && typeof adv.value === "object" && adv.value !== null && !Array.isArray(adv.value);

  React.useEffect(() => {
    if (open) {
      setLabel("");
      setName("");
      setVisibility(KEEP);
      setTags([]);
      setDifficulty(KEEP);
      setPrompt(latestPrompt);
      setConstraints(null);
      setAdvanced("");
      setChangelog("");
      create.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!advValid) return;
    const overrides: Record<string, unknown> = {};
    if (difficulty !== KEEP) overrides.difficulty = difficulty as Difficulty;
    if (latest && !latest.redacted && prompt !== latestPrompt) overrides.input = { ...(latest.input ?? {}), prompt };
    if (constraints) overrides.constraints = constraints;
    Object.assign(overrides, adv.ok ? (adv.value as Record<string, unknown>) : {});
    create.mutate(
      {
        label: label.trim(),
        name: name.trim() || null,
        visibility: visibility === KEEP ? null : (visibility as ScenarioVisibility),
        tags: tags.length ? tags : null,
        overrides: overrides as ScenarioContentInput,
        changelog: changelog.trim(),
      },
      {
        onSuccess: (v) => {
          toast.success("Variante créée", { description: v.name });
          onOpenChange(false);
          router.push(`/scenarios/${v.id}`);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Nouvelle variante</DialogTitle>
            <DialogDescription>
              Même famille que « {scenario.name} » : la robustesse est mesurée sur les variantes. Les champs non modifiés reprennent la
              dernière version.
            </DialogDescription>
          </DialogHeader>
          {create.error && !errors.length ? <Alert tone="red">{create.error.detail}</Alert> : null}
          {errors.length ? (
            <Alert tone="red" title="Variante invalide">
              <ul className="list-disc pl-4">
                {errors.map((er, i) => (
                  <li key={i}>
                    <span className="font-mono text-[12px]">{er.field}</span> : {er.message}
                  </li>
                ))}
              </ul>
            </Alert>
          ) : null}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="var-label" label="Libellé de variante" required hint="Ex. short_context, adversarial" error={fieldError(errors, "label")}>
              <Input id="var-label" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={60} className="font-mono" required />
            </Field>
            <Field id="var-name" label="Nom" hint="Défaut : nom du parent + libellé." error={fieldError(errors, "name")}>
              <Input id="var-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={300} />
            </Field>
            <Field id="var-visibility" label="Visibilité" error={fieldError(errors, "visibility")}>
              <SimpleSelect
                id="var-visibility"
                value={visibility}
                onValueChange={setVisibility}
                options={[
                  { value: KEEP, label: `Identique (${SCENARIO_VISIBILITY_META[scenario.visibility].label})` },
                  ...SCENARIO_VISIBILITIES.map((v) => ({ value: v, label: SCENARIO_VISIBILITY_META[v].label, disabled: v === "private" && !isMaintainer })),
                ]}
              />
            </Field>
            <Field id="var-difficulty" label="Difficulté" error={fieldError(errors, "overrides.difficulty")}>
              <SimpleSelect
                id="var-difficulty"
                value={difficulty}
                onValueChange={setDifficulty}
                options={[{ value: KEEP, label: "Identique" }, ...DIFFICULTIES.map((d) => ({ value: d, label: DIFFICULTY_META[d].label }))]}
              />
            </Field>
            {latest && !latest.redacted ? (
              <Field id="var-prompt" label="Prompt" hint="Modifiez le prompt pour cette variante (laissez tel quel pour le conserver)." className="sm:col-span-2">
                <Textarea id="var-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={4} />
              </Field>
            ) : null}
            <Field id="var-constraints" label="Contraintes" hint={constraints ? "Remplacent celles du parent." : "Vide : contraintes du parent conservées."} className="sm:col-span-2">
              <TagInput id="var-constraints" value={constraints ?? []} onChange={(v) => setConstraints(v.length ? v : null)} placeholder="Ajouter une contrainte puis Entrée" />
            </Field>
            <Field id="var-tags" label="Étiquettes" hint="Vide : celles du parent." className="sm:col-span-2">
              <TagInput id="var-tags" value={tags} onChange={setTags} />
            </Field>
            <JsonField
              id="var-advanced"
              label="Autres remplacements (JSON avancé)"
              hint='Champs de contenu remplacés tels quels, ex. {"context": {"documents": []}}'
              value={advanced}
              onChange={setAdvanced}
              expect="object"
              rows={4}
              className="sm:col-span-2"
            />
            <Field id="var-changelog" label="Journal des modifications" className="sm:col-span-2">
              <Input id="var-changelog" value={changelog} onChange={(e) => setChangelog(e.target.value)} />
            </Field>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={create.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={create.isPending} disabled={!label.trim() || !advValid}>
              Créer la variante
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
