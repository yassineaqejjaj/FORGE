"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Play, Search } from "lucide-react";
import { toast } from "sonner";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { DifficultyBadge } from "@/components/domain/enum-badge";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/client";
import {
  useAgentOptions,
  useAgentVersionOptions,
  useCreateRuns,
  useEvaluationConfigOptions,
  useScenarioOptions,
} from "@/lib/api/runs";
import { scenarioCategoryLabel } from "@/lib/enums";
import { formatDate, plural } from "@/lib/format";
import { cn, normalizeText } from "@/lib/utils";

export interface NewRunDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-selected scenario ids (e.g. from a scenario page). */
  defaultScenarioIds?: string[];
  defaultAgentId?: string;
}

const MAX_REPETITIONS = 20;

/** Ad-hoc run creation (editor+): agent version × scenarios × repetitions + evaluation configuration. */
export function NewRunDialog({ open, onOpenChange, defaultScenarioIds, defaultAgentId }: NewRunDialogProps) {
  const router = useRouter();
  const agents = useAgentOptions(open);
  const scenarios = useScenarioOptions(open);
  const configs = useEvaluationConfigOptions(open);
  const create = useCreateRuns();

  const [agentId, setAgentId] = React.useState<string | undefined>(defaultAgentId);
  const [versionId, setVersionId] = React.useState<string | undefined>();
  const [scenarioIds, setScenarioIds] = React.useState<string[]>(defaultScenarioIds ?? []);
  const [repetitions, setRepetitions] = React.useState("1");
  const [configId, setConfigId] = React.useState<string | undefined>();
  const [filter, setFilter] = React.useState("");
  const versions = useAgentVersionOptions(agentId);

  React.useEffect(() => {
    if (!open) {
      create.reset();
      setFilter("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Default version = latest of the selected agent.
  React.useEffect(() => {
    const list = versions.data;
    if (!list?.length) return;
    if (!versionId || !list.some((v) => v.id === versionId)) {
      const latest = [...list].sort((a, b) => b.version_number - a.version_number)[0];
      setVersionId(latest?.id);
    }
  }, [versions.data, versionId]);

  // Default configuration = the platform default.
  React.useEffect(() => {
    if (configId || !configs.data) return;
    setConfigId((configs.data.items.find((c) => c.is_default) ?? configs.data.items[0])?.id);
  }, [configs.data, configId]);

  const agentItems = (agents.data?.items ?? []).filter((a) => !a.archived);
  const scenarioItems = (scenarios.data?.items ?? []).filter((s) => !s.archived);
  const needle = normalizeText(filter);
  const visibleScenarios = needle
    ? scenarioItems.filter((s) => normalizeText(`${s.name} ${s.slug} ${s.category}`).includes(needle))
    : scenarioItems;
  const selected = new Set(scenarioIds);
  const reps = Math.round(Number(repetitions));
  const repsValid = Number.isFinite(reps) && reps >= 1 && reps <= MAX_REPETITIONS;
  const total = scenarioIds.length * (repsValid ? reps : 0);
  const canSubmit = Boolean(versionId) && scenarioIds.length > 0 && repsValid && !create.isPending;

  const toggle = (id: string, checked: boolean) =>
    setScenarioIds((prev) => (checked ? [...prev, id] : prev.filter((x) => x !== id)));
  const allVisibleSelected = visibleScenarios.length > 0 && visibleScenarios.every((s) => selected.has(s.id));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !versionId) return;
    try {
      const runs = await create.mutateAsync({
        agent_version_id: versionId,
        scenario_ids: scenarioIds,
        scenario_version_ids: [],
        repetitions: reps,
        evaluation_config_id: configId ?? null,
        tags: [],
      });
      toast.success(`${plural(runs.length, "run lancé", "runs lancés")}.`);
      onOpenChange(false);
      if (runs.length === 1 && runs[0]) router.push(`/runs/${runs[0].id}`);
      else router.push(`/runs?agent_version_id=${versionId}&sort=-created_at`);
    } catch {
      // rendered inline below
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-5">
          <DialogHeader>
            <DialogTitle>Nouveau run</DialogTitle>
            <DialogDescription>
              Exécute une version d&apos;agent sur un ou plusieurs scénarios (dernière version), puis l&apos;évalue avec la
              configuration choisie. Le manifeste fige toutes les conditions de l&apos;expérience.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="new-run-agent" label="Agent" required>
              {agents.isPending ? (
                <Skeleton className="h-9 w-full" />
              ) : (
                <SimpleSelect
                  id="new-run-agent"
                  value={agentId}
                  onValueChange={(v) => {
                    setAgentId(v);
                    setVersionId(undefined);
                  }}
                  placeholder={agentItems.length ? "Choisir un agent…" : "Aucun agent"}
                  options={agentItems.map((a) => ({ value: a.id, label: a.name, description: a.provider || a.slug }))}
                  disabled={!agentItems.length}
                />
              )}
            </Field>
            <Field
              id="new-run-version"
              label="Version"
              required
              hint={versions.data && !versions.data.length ? "Cet agent n'a aucune version." : undefined}
            >
              <SimpleSelect
                id="new-run-version"
                value={versionId}
                onValueChange={setVersionId}
                placeholder={agentId ? (versions.isPending ? "Chargement…" : "Choisir une version…") : "Choisir d'abord un agent"}
                disabled={!agentId || !versions.data?.length}
                options={[...(versions.data ?? [])]
                  .sort((a, b) => b.version_number - a.version_number)
                  .map((v) => ({
                    value: v.id,
                    label: `v${v.version}`,
                    description: [v.model, v.changelog, formatDate(v.created_at)].filter(Boolean).join(" · "),
                  }))}
              />
            </Field>
          </div>

          <Field
            id="new-run-scenario-filter"
            label="Scénarios"
            required
            labelAside={`${scenarioIds.length} sélectionné${scenarioIds.length > 1 ? "s" : ""}`}
          >
            <div className="overflow-hidden rounded-lg border border-border">
              <div className="flex items-center gap-2 border-b border-border bg-muted/40 p-2">
                <Input
                  id="new-run-scenario-filter"
                  size="sm"
                  type="search"
                  placeholder="Filtrer par nom, slug ou catégorie…"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  leftIcon={<Search aria-hidden />}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="xs"
                  disabled={!visibleScenarios.length}
                  onClick={() =>
                    setScenarioIds((prev) =>
                      allVisibleSelected
                        ? prev.filter((id) => !visibleScenarios.some((s) => s.id === id))
                        : Array.from(new Set([...prev, ...visibleScenarios.map((s) => s.id)])),
                    )
                  }
                >
                  {allVisibleSelected ? "Tout désélectionner" : "Tout sélectionner"}
                </Button>
              </div>
              <ul className="max-h-64 divide-y divide-border overflow-y-auto" aria-label="Scénarios disponibles">
                {scenarios.isPending ? (
                  Array.from({ length: 4 }, (_, i) => (
                    <li key={i} className="p-2.5">
                      <Skeleton className="h-5 w-full" />
                    </li>
                  ))
                ) : visibleScenarios.length === 0 ? (
                  <li className="p-4 text-center text-[13px] text-muted-foreground">Aucun scénario ne correspond.</li>
                ) : (
                  visibleScenarios.map((s) => {
                    const cid = `new-run-scenario-${s.id}`;
                    return (
                      <li key={s.id}>
                        <label
                          htmlFor={cid}
                          className={cn(
                            "flex cursor-pointer items-center gap-3 px-3 py-2 text-[13px] hover:bg-muted/50",
                            selected.has(s.id) && "bg-brand-soft/50",
                          )}
                        >
                          <Checkbox id={cid} checked={selected.has(s.id)} onCheckedChange={(c) => toggle(s.id, c === true)} />
                          <span className="grid min-w-0 flex-1">
                            <span className="truncate font-medium text-foreground">{s.name}</span>
                            <span className="truncate text-xs text-muted-foreground">
                              {scenarioCategoryLabel(s.category)} · v{s.latest_version}
                              {s.variant_label ? ` · ${s.variant_label}` : ""}
                            </span>
                          </span>
                          <span className="hidden shrink-0 items-center gap-1 sm:flex">
                            {s.difficulty ? <DifficultyBadge value={s.difficulty} withTooltip={false} /> : null}
                            <VisibilityBadge visibility={s.visibility} iconOnly noTooltip />
                            {s.classification >= 2 ? <ClassificationBadge level={s.classification} showLabel={false} noTooltip /> : null}
                          </span>
                        </label>
                      </li>
                    );
                  })
                )}
              </ul>
            </div>
          </Field>

          <div className="grid gap-4 sm:grid-cols-[10rem_minmax(0,1fr)]">
            <Field
              id="new-run-repetitions"
              label="Répétitions"
              required
              error={!repsValid ? `Entre 1 et ${MAX_REPETITIONS}.` : undefined}
            >
              <Input
                id="new-run-repetitions"
                type="number"
                min={1}
                max={MAX_REPETITIONS}
                value={repetitions}
                onChange={(e) => setRepetitions(e.target.value)}
                invalid={!repsValid}
              />
            </Field>
            <Field id="new-run-config" label="Configuration d'évaluation" hint="Pondérations, garde-fous, juges et agrégation.">
              {configs.isPending ? (
                <Skeleton className="h-9 w-full" />
              ) : (
                <SimpleSelect
                  id="new-run-config"
                  value={configId}
                  onValueChange={setConfigId}
                  options={(configs.data?.items ?? []).map((c) => ({
                    value: c.id,
                    label: `${c.name} · v${c.version}`,
                    description: `${c.key}${c.is_default ? " · par défaut" : ""} · seuil ${c.pass_threshold}`,
                  }))}
                />
              )}
            </Field>
          </div>

          {create.isError ? (
            <Alert tone="red" title="Impossible de lancer les runs">
              {errorMessage(create.error)}
            </Alert>
          ) : null}

          <DialogFooter className="sm:justify-between">
            <p className="text-xs text-muted-foreground" aria-live="polite">
              {total > 0 ? `${plural(total, "run")} seront créés.` : "Sélectionnez une version et au moins un scénario."}
            </p>
            <div className="flex flex-col-reverse gap-2 sm:flex-row">
              <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={create.isPending}>
                Annuler
              </Button>
              <Button type="submit" disabled={!canSubmit} loading={create.isPending} leftIcon={<Play aria-hidden />}>
                Lancer {total > 1 ? `${total} runs` : "le run"}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
