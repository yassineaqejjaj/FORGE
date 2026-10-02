"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Lightbulb } from "lucide-react";

import { AgentVersionSelect, ScenarioMultiPicker, type AgentVersionChoice, type ScenarioSelection } from "@/components/benchmarks/pickers";
import { EvaluationConfigSelect } from "@/components/evaluation-configs/config-select";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useAgentVersionDetail, useBenchmarks, type AgentVersionDetail } from "@/lib/api/benchmarks";
import { errorMessage, isApiError } from "@/lib/api/client";
import { useCreateExperiment } from "@/lib/api/experiments";
import { formatNumber } from "@/lib/format";

export interface ExperimentFormDefaults {
  benchmarkId?: string | null;
  baselineVersionId?: string | null;
  candidateVersionId?: string | null;
  sourceFeedbackReportId?: string | null;
}

function choiceFromDetail(v: AgentVersionDetail): AgentVersionChoice {
  return { id: v.id, label: v.label, agent_id: v.agent_id, content_hash: v.content_hash };
}

/** Create and launch a baseline vs candidate experiment (editor+). */
export function ExperimentFormDialog({
  open,
  onOpenChange,
  defaults = {},
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaults?: ExperimentFormDefaults;
}) {
  const router = useRouter();
  const create = useCreateExperiment();
  const benchmarks = useBenchmarks({ page_size: 200 });
  const baselineDefault = useAgentVersionDetail(open ? defaults.baselineVersionId : null);
  const candidateDefault = useAgentVersionDetail(open ? defaults.candidateVersionId : null);

  const [baseline, setBaseline] = React.useState<AgentVersionChoice | null>(null);
  const [candidate, setCandidate] = React.useState<AgentVersionChoice | null>(null);
  const [source, setSource] = React.useState<"benchmark" | "scenarios">("benchmark");
  const [benchmarkId, setBenchmarkId] = React.useState<string | undefined>(defaults.benchmarkId ?? undefined);
  const [scenarios, setScenarios] = React.useState<ScenarioSelection[]>([]);
  const [repetitions, setRepetitions] = React.useState("");
  const [configId, setConfigId] = React.useState<string | null>(null);
  const [name, setName] = React.useState("");
  const [hypothesis, setHypothesis] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [submitted, setSubmitted] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setBaseline(null);
    setCandidate(null);
    setSource("benchmark");
    setBenchmarkId(defaults.benchmarkId ?? undefined);
    setScenarios([]);
    setRepetitions("");
    setConfigId(null);
    setName("");
    setHypothesis("");
    setDescription("");
    setSubmitted(false);
    create.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when the dialog opens
  }, [open]);

  React.useEffect(() => {
    if (baselineDefault.data && !baseline) setBaseline(choiceFromDetail(baselineDefault.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- prefill once loaded
  }, [baselineDefault.data]);
  React.useEffect(() => {
    if (candidateDefault.data && !candidate) setCandidate(choiceFromDetail(candidateDefault.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- prefill once loaded
  }, [candidateDefault.data]);

  const benchmark = benchmarks.data?.items.find((b) => b.id === benchmarkId);
  const reps = repetitions.trim() ? Number(repetitions) : null;
  const repsValid = reps === null || (Number.isInteger(reps) && reps >= 1 && reps <= 20);
  const sameVersion = Boolean(baseline && candidate && baseline.id === candidate.id);
  const sameHash = Boolean(baseline && candidate && !sameVersion && baseline.content_hash === candidate.content_hash);
  const errors = {
    baseline: !baseline ? "Choisissez la version baseline." : undefined,
    candidate: !candidate ? "Choisissez la version candidate." : sameVersion ? "La candidate doit différer de la baseline." : undefined,
    source:
      source === "benchmark" ? (!benchmarkId ? "Choisissez un benchmark." : undefined) : scenarios.length === 0 ? "Sélectionnez au moins un scénario." : undefined,
    repetitions: !repsValid ? "Entre 1 et 20 répétitions." : undefined,
  };
  const valid = !Object.values(errors).some(Boolean);
  const nScenarios = source === "benchmark" ? (benchmark?.n_scenarios ?? 0) : scenarios.length;
  const effectiveReps = reps ?? (source === "benchmark" ? (benchmark?.repetitions ?? 1) : 1);
  const runCount = 2 * nScenarios * effectiveReps;
  const fieldErrors = isApiError(create.error) ? create.error.fieldErrors : {};

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (!valid || !baseline || !candidate) return;
    const pinned = scenarios.filter((s) => s.scenario_version_id).map((s) => s.scenario_version_id as string);
    const latest = scenarios.filter((s) => !s.scenario_version_id).map((s) => s.scenario_id);
    const created = await create.mutateAsync({
      baseline_version_id: baseline.id,
      candidate_version_id: candidate.id,
      benchmark_id: source === "benchmark" ? benchmarkId : undefined,
      scenario_ids: source === "scenarios" && latest.length ? latest : undefined,
      scenario_version_ids: source === "scenarios" && pinned.length ? pinned : undefined,
      repetitions: reps ?? undefined,
      evaluation_config_id: configId ?? undefined,
      name: name.trim() || undefined,
      hypothesis: hypothesis.trim(),
      description: description.trim(),
      source_feedback_report_id: defaults.sourceFeedbackReportId ?? undefined,
      trigger: "ui",
    });
    onOpenChange(false);
    router.push(`/experiments/${created.id}`);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent size="xl">
        <form onSubmit={submit} className="grid gap-5" noValidate>
          <DialogHeader>
            <DialogTitle>Nouvelle expérience</DialogTitle>
            <DialogDescription>
              Compare une version candidate à une baseline sur les mêmes versions de scénarios, avec la même configuration
              de score : la comparaison appariée dit si la candidate est réellement meilleure.
            </DialogDescription>
          </DialogHeader>

          {defaults.sourceFeedbackReportId ? (
            <Alert tone="violet" icon={<Lightbulb aria-hidden />} title="Boucle d'amélioration">
              Cette expérience sera rattachée au rapport de feedback qui a motivé la version candidate.
            </Alert>
          ) : null}

          <div className="grid items-start gap-4 lg:grid-cols-[1fr_auto_1fr]">
            <Field id="xp-baseline" label="Baseline (version en production)" required error={submitted ? errors.baseline : fieldErrors.baseline_version_id}>
              <AgentVersionSelect id="xp-baseline" label="Baseline" value={baseline} onChange={setBaseline} invalid={submitted && Boolean(errors.baseline)} />
            </Field>
            <ArrowRight className="mt-8 hidden size-4 text-muted-foreground lg:block" aria-hidden />
            <Field id="xp-candidate" label="Candidate" required error={submitted ? errors.candidate : fieldErrors.candidate_version_id}>
              <AgentVersionSelect id="xp-candidate" label="Candidate" value={candidate} onChange={setCandidate} invalid={submitted && Boolean(errors.candidate)} />
            </Field>
          </div>
          {sameHash ? (
            <Alert tone="amber" title="Contenu identique">
              Baseline et candidate ont la même empreinte de contenu : toute différence mesurée sera du bruit (utile pour
              estimer la variance de l&apos;agent).
            </Alert>
          ) : null}

          <div className="grid gap-3">
            <SegmentedControl
              aria-label="Source des scénarios"
              value={source}
              onValueChange={setSource}
              options={[
                { value: "benchmark", label: "Depuis un benchmark" },
                { value: "scenarios", label: "Liste de scénarios" },
              ]}
            />
            {source === "benchmark" ? (
              <Field id="xp-benchmark" label="Benchmark" required error={submitted ? errors.source : fieldErrors.benchmark_id} hint="Mêmes versions de scénarios et configuration que le benchmark.">
                <SimpleSelect
                  id="xp-benchmark"
                  invalid={submitted && Boolean(errors.source)}
                  placeholder={benchmarks.isPending ? "Chargement…" : "Choisir un benchmark…"}
                  value={benchmarkId}
                  onValueChange={setBenchmarkId}
                  options={(benchmarks.data?.items ?? []).map((b) => ({
                    value: b.id,
                    label: b.name,
                    description: `${b.slug} · ${b.n_scenarios} scénarios · ${b.repetitions} rép.`,
                  }))}
                />
              </Field>
            ) : (
              <Field id="xp-scenarios" label="Scénarios" required error={submitted ? errors.source : undefined}>
                <ScenarioMultiPicker id="xp-scenarios" value={scenarios} onChange={setScenarios} invalid={submitted && Boolean(errors.source)} />
              </Field>
            )}
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <Field
              id="xp-reps"
              label="Répétitions"
              hint={source === "benchmark" ? "Vide = celles du benchmark" : "Vide = 1 ; ≥ 2 pour mesurer le bruit"}
              error={submitted ? errors.repetitions : undefined}
            >
              <Input id="xp-reps" type="number" min={1} max={20} value={repetitions} onChange={(e) => setRepetitions(e.target.value)} placeholder={String(effectiveReps)} />
            </Field>
            <Field id="xp-config" label="Configuration d'évaluation" className="md:col-span-2" hint="Par défaut : celle du benchmark, sinon la configuration par défaut.">
              <EvaluationConfigSelect id="xp-config" value={configId} onChange={setConfigId} defaultLabel="Configuration du benchmark / par défaut" />
            </Field>
            <Field id="xp-name" label="Nom" className="md:col-span-3" hint="Vide = « baseline → candidate »">
              <Input id="xp-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="PR #142 : recherche ciblée" />
            </Field>
            <Field id="xp-hypothesis" label="Hypothèse" className="md:col-span-3">
              <Textarea
                id="xp-hypothesis"
                rows={2}
                value={hypothesis}
                onChange={(e) => setHypothesis(e.target.value)}
                placeholder="La recherche ciblée améliore la qualité et réduit le coût, sans dégrader la sécurité."
              />
            </Field>
            <Field id="xp-description" label="Description" className="md:col-span-3">
              <Textarea id="xp-description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
          </div>

          <Alert tone="sky" title={`${formatNumber(runCount, 0)} runs`}>
            2 bras × {nScenarios || "?"} scénario(s) × {effectiveReps} répétition(s). Avec moins de 6 scénarios appariés,
            aucun écart ne peut être statistiquement significatif.
          </Alert>
          {create.error ? <Alert tone="red">{errorMessage(create.error)}</Alert> : null}

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={create.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={create.isPending}>
              Lancer l&apos;expérience
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
