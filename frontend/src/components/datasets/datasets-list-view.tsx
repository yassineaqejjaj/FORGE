"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Database, Plus, Search } from "lucide-react";

import { RequireRole } from "@/components/auth/require-role";
import { TableSkeleton } from "@/components/benchmarks/common";
import { pageFrom, useUrlSearch, useUrlState } from "@/components/benchmarks/use-url-state";
import { RelativeTime } from "@/components/domain/relative-time";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { isApiError } from "@/lib/api/client";
import { DATASET_KIND_META, useCreateDataset, useDatasets, type DatasetKind } from "@/lib/api/datasets";

const PAGE_SIZE = 25;
const KINDS: DatasetKind[] = ["context", "gold"];

export function DatasetKindBadge({ kind }: { kind: DatasetKind }) {
  return (
    <Badge tone={kind === "gold" ? "amber" : "blue"} size="sm">
      {DATASET_KIND_META[kind].label}
    </Badge>
  );
}

function CreateDatasetForm({ onDone, onBusyChange }: { onDone: () => void; onBusyChange: (busy: boolean) => void }) {
  const router = useRouter();
  const create = useCreateDataset();
  const [name, setName] = React.useState("");
  const [kind, setKind] = React.useState<DatasetKind>("context");
  const [description, setDescription] = React.useState("");

  React.useEffect(() => onBusyChange(create.isPending), [create.isPending, onBusyChange]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || create.isPending) return;
    create.mutate(
      { name: name.trim(), kind, description },
      {
        onSuccess: (dataset) => {
          toast.success("Dataset créé");
          onDone();
          router.push(`/datasets/${dataset.id}`);
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>Nouveau dataset</DialogTitle>
        <DialogDescription>
          Un dataset de contexte regroupe les documents fournis aux agents ; un dataset gold liste des exécutions de
          référence à noter par des humains pour calibrer les juges.
        </DialogDescription>
      </DialogHeader>
      {create.error ? (
        <Alert tone="red" title="Création impossible">
          {isApiError(create.error) ? create.error.detail : "Erreur inattendue"}
        </Alert>
      ) : null}
      <Field id="dataset-name" label="Nom" required>
        <Input id="dataset-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} autoFocus required />
      </Field>
      <Field id="dataset-kind" label="Type">
        <SegmentedControl
          aria-label="Type de dataset"
          value={kind}
          onValueChange={(v) => setKind(v as DatasetKind)}
          options={KINDS.map((k) => ({ value: k, label: DATASET_KIND_META[k].label }))}
        />
      </Field>
      <p className="-mt-2 text-[12.5px] text-muted-foreground">{DATASET_KIND_META[kind].description}</p>
      <Field id="dataset-description" label="Description">
        <Textarea id="dataset-description" value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
      </Field>
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onDone} disabled={create.isPending}>
          Annuler
        </Button>
        <Button type="submit" loading={create.isPending} disabled={!name.trim()}>
          Créer
        </Button>
      </DialogFooter>
    </form>
  );
}

function CreateDatasetDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [busy, setBusy] = React.useState(false);
  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent size="md">
        {/* Mounted only while open: every opening starts from an empty form. */}
        {open ? <CreateDatasetForm onDone={() => onOpenChange(false)} onBusyChange={setBusy} /> : null}
      </DialogContent>
    </Dialog>
  );
}

/** « Concevoir › Datasets » : context corpora and gold sets. */
export function DatasetsListView() {
  const router = useRouter();
  const { get, set } = useUrlState();
  const search = useUrlSearch("q");
  const page = pageFrom(get("page"));
  const kindParam = get("kind");
  const kind = kindParam === "context" || kindParam === "gold" ? kindParam : undefined;
  const createOpen = get("new") === "1";

  const query = useDatasets({ page, page_size: PAGE_SIZE, kind, q: search.applied || undefined });
  const items = query.data?.items ?? [];
  const filtered = Boolean(kind || search.applied);

  return (
    <>
      <PageHeader
        eyebrow="Concevoir"
        title="Datasets"
        icon={<Database />}
        description="Les données des scénarios : documents de contexte fournis aux agents et jeux gold notés par des humains pour calibrer les juges."
        actions={
          <RequireRole min="editor">
            <Button leftIcon={<Plus aria-hidden />} onClick={() => set({ new: "1" })}>
              Nouveau dataset
            </Button>
          </RequireRole>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden />
          <Input
            aria-label="Rechercher un dataset"
            placeholder="Rechercher un dataset…"
            value={search.value}
            onChange={(e) => search.setValue(e.target.value)}
            className="pl-8"
          />
        </div>
        <SegmentedControl
          aria-label="Type"
          value={kind ?? "all"}
          onValueChange={(v) => set({ kind: v === "all" ? null : v, page: null })}
          options={[{ value: "all", label: "Tous" }, ...KINDS.map((k) => ({ value: k, label: DATASET_KIND_META[k].label }))]}
        />
      </div>

      {query.isError && !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <Card>
          {query.isPending ? (
            <TableSkeleton rows={5} />
          ) : items.length === 0 ? (
            <EmptyState
              icon={<Database />}
              title={filtered ? "Aucun dataset ne correspond" : "Aucun dataset pour l'instant"}
              description={
                filtered
                  ? "Élargissez la recherche ou changez de type."
                  : "Créez un dataset de contexte pour vos scénarios, ou un dataset gold pour la calibration."
              }
            />
          ) : (
            <Table dense>
              <TableHeader>
                <TableRow>
                  <TableHead>Nom</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right">Éléments</TableHead>
                  <TableHead className="hidden md:table-cell">Description</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Mis à jour</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((d) => (
                  <TableRow key={d.id} className="cursor-pointer" onClick={() => router.push(`/datasets/${d.id}`)}>
                    <TableCell>
                      <Link href={`/datasets/${d.id}`} className="font-medium text-foreground hover:underline" onClick={(e) => e.stopPropagation()}>
                        {d.name}
                      </Link>
                      <div className="font-mono text-[11px] text-muted-foreground">{d.slug}</div>
                    </TableCell>
                    <TableCell>
                      <DatasetKindBadge kind={d.kind} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{d.items_count}</TableCell>
                    <TableCell className="hidden max-w-md truncate text-muted-foreground md:table-cell">{d.description || "—"}</TableCell>
                    <TableCell className="hidden text-right sm:table-cell">
                      <RelativeTime date={d.updated_at} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Card>
      )}

      {query.data && query.data.total > PAGE_SIZE ? (
        <Pagination
          className="mt-4"
          page={page}
          pageSize={PAGE_SIZE}
          total={query.data.total}
          onPageChange={(p) => set({ page: p === 1 ? null : p })}
        />
      ) : null}

      <CreateDatasetDialog open={createOpen} onOpenChange={(open) => set({ new: open ? "1" : null })} />
    </>
  );
}
