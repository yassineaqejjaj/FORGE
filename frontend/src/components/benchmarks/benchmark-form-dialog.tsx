"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { EvaluationConfigSelect } from "@/components/evaluation-configs/config-select";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  useCreateBenchmark,
  useUpdateBenchmark,
  type BenchmarkDetail,
} from "@/lib/api/benchmarks";
import { errorMessage, isApiError } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";
import { slugify } from "@/lib/utils";
import { AgentVersionMultiPicker, ScenarioMultiPicker, type AgentVersionChoice, type ScenarioSelection } from "./pickers";

export interface BenchmarkFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Edit mode when provided. */
  benchmark?: BenchmarkDetail;
}

function initialScenarios(b?: BenchmarkDetail): ScenarioSelection[] {
  return (b?.scenarios ?? [])
    .slice()
    .sort((x, y) => x.position - y.position)
    .map((s) => ({
      scenario_id: s.scenario_id,
      scenario_version_id: s.scenario_version_id ?? null,
      name: s.name,
      visibility: s.visibility,
      classification: s.classification,
      latest_version: s.latest_version,
      pinned_version: s.pinned_version ?? null,
    }));
}

function initialAgents(b?: BenchmarkDetail): AgentVersionChoice[] {
  return (b?.agents ?? []).map((a) => ({
    id: a.agent_version_id,
    label: a.label,
    agent_id: a.agent_id,
    content_hash: a.content_hash,
  }));
}

/** Create / edit a benchmark (editor+): scenarios × agent versions × repetitions + configuration. */
export function BenchmarkFormDialog({ open, onOpenChange, benchmark }: BenchmarkFormDialogProps) {
  const router = useRouter();
  const editing = Boolean(benchmark);
  const create = useCreateBenchmark();
  const update = useUpdateBenchmark(benchmark?.id ?? "");
  const mutation = editing ? update : create;

  const [name, setName] = React.useState(benchmark?.name ?? "");
  const [slug, setSlug] = React.useState(benchmark?.slug ?? "");
  const [slugTouched, setSlugTouched] = React.useState(editing);
  const [description, setDescription] = React.useState(benchmark?.description ?? "");
  const [repetitions, setRepetitions] = React.useState(String(benchmark?.repetitions ?? 1));
  const [configId, setConfigId] = React.useState<string | null>(benchmark?.evaluation_config_id ?? null);
  const [tags, setTags] = React.useState((benchmark?.tags ?? []).join(", "));
  const [scenarios, setScenarios] = React.useState<ScenarioSelection[]>(() => initialScenarios(benchmark));
  const [agents, setAgents] = React.useState<AgentVersionChoice[]>(() => initialAgents(benchmark));
  const [submitted, setSubmitted] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setName(benchmark?.name ?? "");
    setSlug(benchmark?.slug ?? "");
    setSlugTouched(Boolean(benchmark));
    setDescription(benchmark?.description ?? "");
    setRepetitions(String(benchmark?.repetitions ?? 1));
    setConfigId(benchmark?.evaluation_config_id ?? null);
    setTags((benchmark?.tags ?? []).join(", "));
    setScenarios(initialScenarios(benchmark));
    setAgents(initialAgents(benchmark));
    setSubmitted(false);
    create.reset();
    update.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the dialog opens
  }, [open]);

  const reps = Number(repetitions);
  const repsValid = Number.isInteger(reps) && reps >= 1 && reps <= 20;
  const errors = {
    name: !name.trim() ? "Le nom est obligatoire." : undefined,
    scenarios: scenarios.length === 0 ? "Sélectionnez au moins un scénario." : undefined,
    agents: agents.length === 0 ? "Sélectionnez au moins une version d'agent." : undefined,
    repetitions: !repsValid ? "Entre 1 et 20 répétitions." : undefined,
  };
  const valid = !Object.values(errors).some(Boolean);
  const runCount = scenarios.length * agents.length * (repsValid ? reps : 0);
  const apiError = mutation.error;
  const fieldErrors = isApiError(apiError) ? apiError.fieldErrors : {};

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (!valid) return;
    const body = {
      name: name.trim(),
      slug: slug.trim() || undefined,
      description: description.trim(),
      repetitions: reps,
      evaluation_config_id: configId ?? undefined,
      scenarios: scenarios.map((s) => ({ scenario_id: s.scenario_id, scenario_version_id: s.scenario_version_id })),
      agent_version_ids: agents.map((a) => a.id),
      tags: tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
    };
    if (editing) {
      await update.mutateAsync(body);
      onOpenChange(false);
    } else {
      const created = await create.mutateAsync(body);
      onOpenChange(false);
      router.push(`/benchmarks/${created.id}`);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !mutation.isPending && onOpenChange(o)}>
      <DialogContent size="xl">
        <form onSubmit={submit} className="grid gap-5" noValidate>
          <DialogHeader>
            <DialogTitle>{editing ? "Modifier le benchmark" : "Nouveau benchmark"}</DialogTitle>
            <DialogDescription>
              Scénarios (version épinglée ou dernière) × versions d&apos;agents × répétitions, évalués avec une
              configuration de score. Les exécutions passées gardent leur matrice figée.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 md:grid-cols-2">
            <Field id="bm-name" label="Nom" required error={submitted ? errors.name : fieldErrors.name}>
              <Input
                id="bm-name"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  if (!slugTouched) setSlug(slugify(e.target.value));
                }}
                invalid={submitted && Boolean(errors.name)}
                autoFocus
              />
            </Field>
            <Field id="bm-slug" label="Identifiant (slug)" hint="Utilisé par la CLI : forge benchmark run <slug>" error={fieldErrors.slug}>
              <Input
                id="bm-slug"
                value={slug}
                onChange={(e) => {
                  setSlug(e.target.value);
                  setSlugTouched(true);
                }}
                className="font-mono"
                placeholder="product-agent-core"
              />
            </Field>
            <Field id="bm-description" label="Description" className="md:col-span-2">
              <Textarea id="bm-description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
          </div>

          <Field id="bm-scenarios" label="Scénarios" required error={submitted ? errors.scenarios : fieldErrors.scenarios}>
            <ScenarioMultiPicker id="bm-scenarios" value={scenarios} onChange={setScenarios} invalid={submitted && Boolean(errors.scenarios)} />
          </Field>

          <Field id="bm-agents" label="Versions d'agents" required error={submitted ? errors.agents : fieldErrors.agent_version_ids}>
            <AgentVersionMultiPicker id="bm-agents" value={agents} onChange={setAgents} invalid={submitted && Boolean(errors.agents)} />
          </Field>

          <div className="grid gap-4 md:grid-cols-3">
            <Field id="bm-reps" label="Répétitions" required hint="Mesure le bruit et la robustesse (1–20)" error={submitted ? errors.repetitions : undefined}>
              <Input
                id="bm-reps"
                type="number"
                min={1}
                max={20}
                value={repetitions}
                onChange={(e) => setRepetitions(e.target.value)}
                invalid={submitted && Boolean(errors.repetitions)}
              />
            </Field>
            <Field id="bm-config" label="Configuration d'évaluation" className="md:col-span-2">
              <EvaluationConfigSelect id="bm-config" value={configId} onChange={setConfigId} allowDefault={!editing} />
            </Field>
            <Field id="bm-tags" label="Étiquettes" hint="Séparées par des virgules" className="md:col-span-3">
              <Input id="bm-tags" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="core, ci" />
            </Field>
          </div>

          <Alert tone="sky" title={`${formatNumber(runCount, 0)} runs par lancement`}>
            {scenarios.length} scénario(s) × {agents.length} version(s) d&apos;agent × {repsValid ? reps : "?"} répétition(s).
          </Alert>

          {apiError ? <Alert tone="red">{errorMessage(apiError)}</Alert> : null}

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              {editing ? "Enregistrer" : "Créer le benchmark"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
