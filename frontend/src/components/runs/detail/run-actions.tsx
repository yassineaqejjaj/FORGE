"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Ban, Braces, FlaskConical, Gauge, Layers, MoreHorizontal, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { JsonViewer } from "@/components/ui/json-viewer";
import { SimpleSelect } from "@/components/ui/select";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentUser } from "@/hooks/use-current-user";
import { errorMessage } from "@/lib/api/client";
import {
  isRunActive,
  useCancelRun,
  useEvaluateRun,
  useEvaluationConfigOptions,
  useRetryRun,
  useRunManifest,
  type RunDetail,
} from "@/lib/api/runs";

function ReevaluateDialog({ run, open, onOpenChange, onQueued }: { run: RunDetail; open: boolean; onOpenChange: (o: boolean) => void; onQueued: () => void }) {
  const configs = useEvaluationConfigOptions(open);
  const evaluate = useEvaluateRun(run.id);
  const currentId = typeof run.evaluation_config.id === "string" ? run.evaluation_config.id : undefined;
  const [configId, setConfigId] = React.useState<string | undefined>(currentId);

  React.useEffect(() => {
    if (open) {
      setConfigId(currentId);
      evaluate.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const options = (configs.data?.items ?? []).map((c) => ({
    value: c.id,
    label: `${c.name} · v${c.version}`,
    description: `${c.key}${c.id === currentId ? " · configuration actuelle du run" : ""}${c.is_default ? " · par défaut" : ""}`,
  }));
  if (currentId && !options.some((o) => o.value === currentId)) {
    options.unshift({
      value: currentId,
      label: `${String(run.evaluation_config.name ?? run.evaluation_config.key ?? "Configuration")} · v${String(run.evaluation_config.version ?? "")}`,
      description: "configuration actuelle du run",
    });
  }

  const submit = async () => {
    try {
      const res = await evaluate.mutateAsync({ evaluationConfigId: configId === currentId ? null : configId });
      toast.success(`Ré-évaluation en file : round ${res.next_round}.`);
      onOpenChange(false);
      onQueued();
    } catch {
      // inline
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !evaluate.isPending && onOpenChange(o)}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Ré-évaluer le run</DialogTitle>
          <DialogDescription>
            Crée un nouveau round d&apos;évaluation (règles, métriques, juges) sans ré-exécuter l&apos;agent. Les rounds précédents
            restent consultables ; les évaluations humaines s&apos;appliquent à tous les rounds.
          </DialogDescription>
        </DialogHeader>
        <Field id="reevaluate-config" label="Configuration d'évaluation" hint="Une autre configuration permet de comparer pondérations, garde-fous et juges sur la même sortie.">
          {configs.isPending ? (
            <Skeleton className="h-9 w-full" />
          ) : (
            <SimpleSelect id="reevaluate-config" value={configId} onValueChange={setConfigId} options={options} />
          )}
        </Field>
        {evaluate.isError ? <Alert tone="red" title="Ré-évaluation impossible">{errorMessage(evaluate.error)}</Alert> : null}
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={evaluate.isPending}>
            Annuler
          </Button>
          <Button onClick={() => void submit()} loading={evaluate.isPending} leftIcon={<Gauge aria-hidden />}>
            Lancer le round {run.evaluation_round + 1}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ManifestSheet({ run, open, onOpenChange }: { run: RunDetail; open: boolean; onOpenChange: (o: boolean) => void }) {
  const manifest = useRunManifest(run.id, open);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent size="xl">
        <SheetHeader>
          <SheetTitle>Manifeste du run</SheetTitle>
          <SheetDescription>
            Conditions figées à la création (scénario, agent sans secrets, configuration d&apos;évaluation) — l&apos;exécution et l&apos;évaluation
            ne lisent que ce document.
          </SheetDescription>
          <p className="break-all font-mono text-[11px] text-muted-foreground">{run.manifest_hash}</p>
        </SheetHeader>
        <SheetBody className="grid content-start gap-3">
          {manifest.isPending ? (
            <Skeleton className="h-96 w-full" />
          ) : manifest.isError ? (
            <ErrorState error={manifest.error} onRetry={() => void manifest.refetch()} />
          ) : (
            <>
              {manifest.data.redacted ? (
                <RedactedNotice description="Le contenu du scénario privé est masqué dans ce manifeste ; les identifiants, versions et empreintes restent visibles." />
              ) : null}
              <JsonViewer data={manifest.data.manifest} defaultExpandDepth={2} maxHeightClassName="max-h-[calc(100dvh-14rem)]" />
            </>
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}

/** Run Detail actions: re-evaluate (editor+), retry, cancel, manifest JSON, links to benchmark / experiment. */
export function RunActions({ run, onReevaluated }: { run: RunDetail; onReevaluated: () => void }) {
  const router = useRouter();
  const { hasRole } = useCurrentUser();
  const canEdit = hasRole("editor");
  const [reevaluateOpen, setReevaluateOpen] = React.useState(false);
  const [cancelOpen, setCancelOpen] = React.useState(false);
  const [manifestOpen, setManifestOpen] = React.useState(false);
  const cancel = useCancelRun(run.id);
  const retry = useRetryRun(run.id);
  const active = isRunActive(run.status);
  const canReevaluate = run.status === "completed" || run.status === "failed";

  const doRetry = async () => {
    try {
      const created = await retry.mutateAsync();
      router.push(`/runs/${created.id}`);
    } catch {
      // toast from the mutation cache
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      {run.experiment_id ? (
        <Button asChild variant="ghost" size="sm">
          <Link href={`/experiments/${run.experiment_id}`}>
            <FlaskConical aria-hidden />
            {run.experiment_name ? `Expérience « ${run.experiment_name} »` : "Expérience"}
          </Link>
        </Button>
      ) : null}
      {run.benchmark_id ? (
        <Button asChild variant="ghost" size="sm">
          <Link href={`/benchmarks/${run.benchmark_id}`}>
            <Layers aria-hidden />
            Benchmark
          </Link>
        </Button>
      ) : null}
      <Button variant="secondary" size="sm" leftIcon={<Braces aria-hidden />} onClick={() => setManifestOpen(true)}>
        Manifeste
      </Button>
      <RequireRole min="editor">
        {active ? (
          <Button variant="destructive-outline" size="sm" leftIcon={<Ban aria-hidden />} onClick={() => setCancelOpen(true)}>
            Annuler
          </Button>
        ) : (
          <Button size="sm" leftIcon={<Gauge aria-hidden />} onClick={() => setReevaluateOpen(true)} disabled={!canReevaluate}>
            Ré-évaluer
          </Button>
        )}
      </RequireRole>
      {canEdit && !active ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Autres actions">
              <MoreHorizontal aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => void doRetry()} disabled={retry.isPending}>
              <RotateCcw aria-hidden />
              Nouvel essai (nouveau run, même manifeste)
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link href={`/runs?scenario_id=${run.scenario.id}&agent_version_id=${String(run.agent.agent_version_id ?? "")}`}>
                <Layers aria-hidden />
                Runs du même scénario et de la même version
              </Link>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}

      <ReevaluateDialog run={run} open={reevaluateOpen} onOpenChange={setReevaluateOpen} onQueued={onReevaluated} />
      <ManifestSheet run={run} open={manifestOpen} onOpenChange={setManifestOpen} />
      <ConfirmDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title="Annuler ce run ?"
        description="L'exécution ou l'évaluation en cours est interrompue ; le run passe au statut « Annulé ». Cette action est journalisée."
        confirmLabel="Annuler le run"
        cancelLabel="Conserver"
        destructive
        loading={cancel.isPending}
        onConfirm={async () => {
          await cancel.mutateAsync().catch(() => undefined);
          setCancelOpen(false);
        }}
      />
    </div>
  );
}
