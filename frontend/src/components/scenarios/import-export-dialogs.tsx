"use client";

import * as React from "react";
import { toast } from "sonner";
import { CircleCheck, CircleX, Download, FileUp, MinusCircle, PlusCircle, RefreshCw, Upload } from "lucide-react";

import { ClassificationBanner } from "@/components/domain/classification-banner";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { useExportScenarios, useImportScenarios, type ImportReport, type ScenarioExportParams } from "@/lib/api/scenarios";
import { formatBytes, plural } from "@/lib/format";
import { cn } from "@/lib/utils";

const ACCEPT = ".yaml,.yml,.json,application/json,application/yaml,text/yaml";

/** Import a `forge.scenarios/v1` bundle: dry run (preview) first, then confirmation. */
export function ImportScenariosDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [file, setFile] = React.useState<File | null>(null);
  const [preview, setPreview] = React.useState<ImportReport | null>(null);
  const [done, setDone] = React.useState<ImportReport | null>(null);
  const importer = useImportScenarios();
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (!open) {
      setFile(null);
      setPreview(null);
      setDone(null);
      importer.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const runPreview = (f: File) => {
    setPreview(null);
    setDone(null);
    importer.mutate({ file: f, dryRun: true }, { onSuccess: setPreview });
  };

  const confirm = () => {
    if (!file) return;
    importer.mutate(
      { file, dryRun: false },
      {
        onSuccess: (report) => {
          setDone(report);
          toast.success("Import terminé", {
            description: `${plural(report.created.length, "scénario créé", "scénarios créés")}, ${plural(report.updated.length, "mis à jour", "mis à jour")}`,
          });
        },
      },
    );
  };

  const report = done ?? preview;
  const hasChanges = Boolean(preview && preview.created.length + preview.updated.length > 0);

  return (
    <Dialog open={open} onOpenChange={(o) => !importer.isPending && onOpenChange(o)}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Importer des scénarios</DialogTitle>
          <DialogDescription>
            Fichier YAML ou JSON au format <span className="font-mono">forge.scenarios/v1</span> (10 Mo max.). Une simulation est
            d&apos;abord effectuée : rien n&apos;est enregistré avant votre confirmation.
          </DialogDescription>
        </DialogHeader>

        <div
          className={cn(
            "flex flex-col items-center gap-2 rounded-lg border border-dashed border-border-strong bg-muted/30 px-4 py-6 text-center",
          )}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files[0];
            if (f) {
              setFile(f);
              runPreview(f);
            }
          }}
        >
          <FileUp className="size-6 text-muted-foreground" aria-hidden />
          {file ? (
            <p className="text-[13px]">
              <span className="font-medium">{file.name}</span> <span className="text-muted-foreground">· {formatBytes(file.size)}</span>
            </p>
          ) : (
            <p className="text-[13px] text-muted-foreground">Déposez un fichier ici ou</p>
          )}
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            className="sr-only"
            id="scenario-import-file"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) {
                setFile(f);
                runPreview(f);
              }
              e.target.value = "";
            }}
          />
          <Button type="button" variant="secondary" size="sm" onClick={() => inputRef.current?.click()} leftIcon={<Upload aria-hidden />}>
            {file ? "Choisir un autre fichier" : "Choisir un fichier"}
          </Button>
        </div>

        {importer.isError ? <Alert tone="red" title="Import impossible">{importer.error.detail}</Alert> : null}
        {importer.isPending && !report ? <p className="text-[13px] text-muted-foreground">Analyse du fichier…</p> : null}

        {report ? (
          <div className="grid gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={done ? "green" : "blue"}>{done ? "Import effectué" : "Simulation"}</Badge>
              <Badge tone="green" icon={<PlusCircle aria-hidden />}>
                {plural(report.created.length, "création")}
              </Badge>
              <Badge tone="blue" icon={<RefreshCw aria-hidden />}>
                {plural(report.updated.length, "mise à jour", "mises à jour")}
              </Badge>
              <Badge tone="neutral" icon={<MinusCircle aria-hidden />}>
                {plural(report.skipped.length, "ignoré", "ignorés")}
              </Badge>
              <Badge tone={report.errors.length ? "red" : "neutral"} icon={<CircleX aria-hidden />}>
                {plural(report.errors.length, "erreur")}
              </Badge>
            </div>
            <ul className="grid max-h-72 gap-1.5 overflow-auto rounded-lg border border-border p-2 text-[13px]">
              {report.created.map((it, i) => (
                <ReportLine key={`c${i}`} tone="green" label="Créé" slug={it.slug} detail={it.versions?.length ? `versions ${it.versions.join(", ")}` : null} />
              ))}
              {report.updated.map((it, i) => (
                <ReportLine key={`u${i}`} tone="blue" label="Nouvelle version" slug={it.slug} detail={it.versions?.length ? `versions ${it.versions.join(", ")}` : it.reason} />
              ))}
              {report.skipped.map((it, i) => (
                <ReportLine key={`s${i}`} tone="neutral" label="Ignoré" slug={it.slug} detail={it.reason} />
              ))}
              {report.errors.map((err, i) => (
                <li key={`e${i}`} className="grid gap-0.5 rounded-md bg-red-50 px-2 py-1.5 text-red-950 dark:bg-red-400/10 dark:text-red-100">
                  <span className="font-medium">
                    {err.slug ?? (err.index !== null && err.index !== undefined ? `Scénario n° ${err.index + 1}` : "Bundle")} : {err.message}
                  </span>
                  {err.errors?.length ? (
                    <ul className="list-disc pl-4 text-xs">
                      {err.errors.map((e, j) => (
                        <li key={j}>
                          {String(e.field ?? "")} {e.field ? ":" : ""} {String(e.message ?? JSON.stringify(e))}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
              {report.created.length + report.updated.length + report.skipped.length + report.errors.length === 0 ? (
                <li className="text-muted-foreground">Le fichier ne contient aucun scénario.</li>
              ) : null}
            </ul>
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={importer.isPending}>
            {done ? "Fermer" : "Annuler"}
          </Button>
          {!done ? (
            <Button
              onClick={confirm}
              loading={importer.isPending && Boolean(preview)}
              disabled={!preview || !hasChanges || importer.isPending}
              leftIcon={<CircleCheck aria-hidden />}
            >
              {preview && !hasChanges ? "Rien à importer" : "Confirmer l'import"}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReportLine({ tone, label, slug, detail }: { tone: "green" | "blue" | "neutral"; label: string; slug?: string | null; detail?: string | null }) {
  return (
    <li className="flex flex-wrap items-center gap-2 px-1 py-0.5">
      <Badge tone={tone}>{label}</Badge>
      <span className="font-mono text-xs">{slug ?? "—"}</span>
      {detail ? <span className="text-xs text-muted-foreground">{detail}</span> : null}
    </li>
  );
}

export interface ExportScenariosDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Filters / ids of the current view. */
  params: Omit<ScenarioExportParams, "format" | "versions">;
  /** Description of what will be exported ("12 scénarios (filtres actuels)"). */
  scopeLabel: string;
  /** Highest classification in scope (warning banner). */
  maxClassification?: number;
}

/** Download a `forge.scenarios/v1` bundle (YAML or JSON) of the current selection. */
export function ExportScenariosDialog({ open, onOpenChange, params, scopeLabel, maxClassification }: ExportScenariosDialogProps) {
  const [format, setFormat] = React.useState<"yaml" | "json">("yaml");
  const [versions, setVersions] = React.useState<"all" | "latest">("all");
  const exporter = useExportScenarios();

  const run = () =>
    exporter.mutate(
      { ...params, format, versions },
      {
        onSuccess: (r) => {
          const notes = [
            r.skippedPrivate ? `${plural(r.skippedPrivate, "scénario privé exclu", "scénarios privés exclus")}` : null,
            r.hiddenRulesRemoved ? `${plural(r.hiddenRulesRemoved, "règle masquée retirée", "règles masquées retirées")}` : null,
          ].filter(Boolean);
          toast.success(`Export téléchargé : ${r.filename}`, { description: notes.join(" · ") || undefined });
          onOpenChange(false);
        },
      },
    );

  return (
    <Dialog open={open} onOpenChange={(o) => !exporter.isPending && onOpenChange(o)}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Exporter des scénarios</DialogTitle>
          <DialogDescription>
            {scopeLabel}. Le contenu des scénarios privés et les règles masquées ne sont exportés que pour les mainteneurs.
          </DialogDescription>
        </DialogHeader>
        <ClassificationBanner level={maxClassification ?? 0} context="export" compact />
        <Field id="export-format" label="Format">
          <SegmentedControl
            aria-label="Format"
            value={format}
            onValueChange={setFormat}
            options={[
              { value: "yaml", label: "YAML" },
              { value: "json", label: "JSON" },
            ]}
          />
        </Field>
        <Field id="export-versions" label="Versions">
          <SegmentedControl
            aria-label="Versions exportées"
            value={versions}
            onValueChange={setVersions}
            options={[
              { value: "all", label: "Toutes les versions" },
              { value: "latest", label: "Dernière version" },
            ]}
          />
        </Field>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={exporter.isPending}>
            Annuler
          </Button>
          <Button onClick={run} loading={exporter.isPending} leftIcon={<Download aria-hidden />}>
            Télécharger
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
