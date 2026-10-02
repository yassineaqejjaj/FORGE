"use client";

import * as React from "react";
import { ChevronDown, ChevronRight, History, X } from "lucide-react";

import { TableSkeleton } from "@/components/benchmarks/common";
import { pageFrom, useUrlState } from "@/components/benchmarks/use-url-state";
import { ActorTypeBadge } from "@/components/domain/enum-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { JsonViewer } from "@/components/ui/json-viewer";
import { Pagination } from "@/components/ui/pagination";
import { SimpleSelect } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useAuditEvents, useUsers, type AuditEvent } from "@/lib/api/settings";
import { formatDateTimePrecise } from "@/lib/format";
import { SectionHeading } from "./common";

const PAGE_SIZE = 50;
const ALL = "__all__";

const TARGET_TYPES: ReadonlyArray<{ value: string; label: string }> = [
  { value: "agent", label: "Agent" },
  { value: "agent_version", label: "Version d'agent" },
  { value: "scenario", label: "Scénario" },
  { value: "evaluation_run", label: "Run" },
  { value: "scenario_version", label: "Version de scénario" },
  { value: "benchmark", label: "Benchmark" },
  { value: "benchmark_execution", label: "Exécution de benchmark" },
  { value: "experiment", label: "Expérience" },
  { value: "judge", label: "Juge" },
  { value: "evaluation_config", label: "Configuration" },
  { value: "dataset", label: "Dataset" },
  { value: "criterion", label: "Critère" },
  { value: "error_type", label: "Type d'erreur" },
  { value: "user", label: "Utilisateur" },
  { value: "api_key", label: "Clé d'API" },
  { value: "credential", label: "Identifiant" },
];

function TextFilter({ param, placeholder, label, className }: { param: string; placeholder: string; label: string; className?: string }) {
  const { get, set } = useUrlState();
  const url = get(param) ?? "";
  const [value, setValue] = React.useState(url);
  const debounced = useDebouncedValue(value, 350);
  React.useEffect(() => setValue(url), [url]);
  React.useEffect(() => {
    if (debounced.trim() !== url) set({ [param]: debounced.trim() || null, page: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- push debounced value only
  }, [debounced]);
  return <Input size="sm" className={className} aria-label={label} placeholder={placeholder} value={value} onChange={(e) => setValue(e.target.value)} />;
}

function AuditRow({ e }: { e: AuditEvent }) {
  const [open, setOpen] = React.useState(false);
  const hasDetails = Object.keys(e.details ?? {}).length > 0;
  return (
    <>
      <TableRow>
        <TableCell className="w-8 pr-0">
          {hasDetails ? (
            <Button variant="ghost" size="icon-xs" aria-expanded={open} aria-label={open ? "Masquer les détails" : "Afficher les détails"} onClick={() => setOpen((o) => !o)}>
              {open ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
            </Button>
          ) : null}
        </TableCell>
        <TableCell className="whitespace-nowrap font-mono text-xs tabular-nums text-muted-foreground">{formatDateTimePrecise(e.created_at)}</TableCell>
        <TableCell>
          <div className="flex items-center gap-1.5">
            <ActorTypeBadge value={e.actor_type} withIcon />
            <span className="truncate text-[13px]">{e.actor_label}</span>
          </div>
        </TableCell>
        <TableCell className="font-mono text-xs">{e.action}</TableCell>
        <TableCell className="hidden lg:table-cell">
          <span className="grid text-xs">
            <span>{e.target_type}</span>
            {e.target_id ? <span className="font-mono text-muted-foreground">{e.target_id.slice(0, 8)}</span> : null}
          </span>
        </TableCell>
        <TableCell className="text-[13px]">{e.summary}</TableCell>
      </TableRow>
      {open ? (
        <TableRow>
          <TableCell colSpan={6} className="bg-muted/30">
            <div className="grid gap-2 py-1">
              <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
                {e.target_id ? <span>Cible : <span className="font-mono">{e.target_id}</span></span> : null}
                {e.actor_id ? <span>Acteur : <span className="font-mono">{e.actor_id}</span></span> : null}
                {e.request_id ? <span>Requête : <span className="font-mono">{e.request_id}</span></span> : null}
              </div>
              <JsonViewer data={e.details} rootLabel="details" defaultExpandDepth={2} maxHeightClassName="max-h-80" />
            </div>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}

export function AuditLog() {
  const { get, set } = useUrlState();
  const { hasRole } = useCurrentUser();
  const isAdmin = hasRole("admin");
  const page = pageFrom(get("page"));
  const targetType = get("target_type") ?? undefined;
  const actorId = get("actor_id") ?? undefined;
  const users = useUsers({ page_size: 200 }, isAdmin);
  const query = useAuditEvents({
    page,
    page_size: PAGE_SIZE,
    action: get("action") ?? undefined,
    target_type: targetType,
    target_id: get("target_id") ?? undefined,
    actor_id: actorId,
  });
  const filtered = Boolean(get("action") || targetType || get("target_id") || actorId);

  return (
    <section aria-labelledby="settings-section-title" className="grid gap-4">
      <SectionHeading title="Journal d'audit" description="Toutes les mutations de la plateforme : qui, quoi, quand, avec les détails enregistrés dans la même transaction." />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <TextFilter param="action" label="Action" placeholder="Action ou préfixe (ex. experiment)" className="w-full sm:w-60" />
          <SimpleSelect
            size="sm"
            className="w-52"
            aria-label="Type de cible"
            value={targetType ?? ALL}
            options={[{ value: ALL, label: "Toutes les cibles" }, ...TARGET_TYPES]}
            onValueChange={(v) => set({ target_type: v === ALL ? null : v, page: null })}
          />
          <TextFilter param="target_id" label="Identifiant de cible" placeholder="Identifiant de cible" className="w-full font-mono sm:w-64" />
          {isAdmin ? (
            <SimpleSelect
              size="sm"
              className="w-56"
              aria-label="Acteur"
              value={actorId ?? ALL}
              options={[{ value: ALL, label: "Tous les acteurs" }, ...(users.data?.items ?? []).map((u) => ({ value: u.id, label: u.full_name, description: u.email }))]}
              onValueChange={(v) => set({ actor_id: v === ALL ? null : v, page: null })}
            />
          ) : (
            <TextFilter param="actor_id" label="Identifiant d'acteur" placeholder="Identifiant d'acteur (UUID)" className="w-full font-mono sm:w-64" />
          )}
          {filtered ? (
            <Button variant="ghost" size="sm" leftIcon={<X aria-hidden />} onClick={() => set({ action: null, target_type: null, target_id: null, actor_id: null, page: null })}>
              Réinitialiser
            </Button>
          ) : null}
          {query.isFetching && !query.isPending ? <Spinner className="ml-auto" /> : null}
        </div>
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} variant="plain" />
        ) : query.isPending ? (
          <TableSkeleton rows={8} />
        ) : query.data.items.length === 0 ? (
          <EmptyState variant="plain" icon={<History />} title="Aucun événement" description={filtered ? "Aucun événement ne correspond à ces filtres." : undefined} />
        ) : (
          <Table dense>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8">
                  <span className="sr-only">Détails</span>
                </TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Acteur</TableHead>
                <TableHead>Action</TableHead>
                <TableHead className="hidden lg:table-cell">Cible</TableHead>
                <TableHead>Résumé</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.items.map((e) => (
                <AuditRow key={e.id} e={e} />
              ))}
            </TableBody>
          </Table>
        )}
        {query.data && query.data.total > PAGE_SIZE ? (
          <div className="border-t border-border p-3">
            <Pagination page={page} pageSize={PAGE_SIZE} total={query.data.total} onPageChange={(p) => set({ page: p > 1 ? p : null })} disabled={query.isFetching} />
          </div>
        ) : null}
      </Card>
    </section>
  );
}
