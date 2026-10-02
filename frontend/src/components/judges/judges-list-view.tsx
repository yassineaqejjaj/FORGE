"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Gavel, Plus, Search } from "lucide-react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { TableSkeleton } from "@/components/benchmarks/common";
import { pageFrom, useUrlSearch, useUrlState } from "@/components/benchmarks/use-url-state";
import { CalibrationStatusBadge, JudgeProviderBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { JudgesAreaTabs } from "@/components/layout/area-tabs";
import { useHasRole } from "@/hooks/use-current-user";
import { errorMessage } from "@/lib/api/client";
import { useForgeMeta } from "@/lib/api/evaluation-configs";
import { useJudges, useJudgesCalibration, useUpdateJudge } from "@/lib/api/judges";
import { JUDGE_PROVIDER_META, JUDGE_PROVIDERS } from "@/lib/enums";
import { formatNumber } from "@/lib/format";

const PAGE_SIZE = 25;
const ALL = "__all__";

export function JudgesListView() {
  const router = useRouter();
  const { get, set } = useUrlState();
  const search = useUrlSearch("q");
  const page = pageFrom(get("page"));
  const provider = get("provider") ?? undefined;
  const enabledParam = get("enabled");
  const allVersions = get("versions") === "all";
  const canEdit = useHasRole("maintainer");
  const meta = useForgeMeta();
  const calibration = useJudgesCalibration();
  const update = useUpdateJudge();

  const query = useJudges({
    page,
    page_size: PAGE_SIZE,
    q: search.applied || undefined,
    provider,
    enabled: enabledParam === null ? undefined : enabledParam === "true",
    latest_only: !allVersions,
  });
  const items = query.data?.items ?? [];
  const calByKey = new Map((calibration.data?.by_judge ?? []).map((m) => [m.judge_key ?? m.key, m]));

  return (
    <>
      <PageHeader
        eyebrow="Configuration"
        title="Juges"
        icon={<Gavel />}
        description="Juges LLM et heuristiques versionnés : fournisseur, modèle, prompt système et grille. Chaque version est immuable et peut être testée sur un run existant."
        actions={
          <RequireRole min="maintainer">
            <Button asChild>
              <Link href="/judges/new">
                <Plus aria-hidden /> Nouveau juge
              </Link>
            </Button>
          </RequireRole>
        }
      >
        <JudgesAreaTabs />
      </PageHeader>
      {meta.data && !meta.data.capabilities.llm_judges_configured ? (
        <Alert tone="sky" className="mb-4" title="Aucun juge LLM configuré au démarrage">
          Seul le juge heuristique hors ligne est disponible par défaut. Créez un identifiant fournisseur (Paramètres →
          Identifiants) puis un juge OpenAI-compatible ou Anthropic.
        </Alert>
      ) : null}
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <Input
            size="sm"
            leftIcon={<Search aria-hidden />}
            placeholder="Rechercher un juge…"
            value={search.value}
            onChange={(e) => search.setValue(e.target.value)}
            className="w-full sm:w-64"
            aria-label="Rechercher un juge"
          />
          <SimpleSelect
            size="sm"
            className="w-44"
            aria-label="Fournisseur"
            value={provider ?? ALL}
            options={[{ value: ALL, label: "Tous les fournisseurs" }, ...JUDGE_PROVIDERS.map((p) => ({ value: p, label: JUDGE_PROVIDER_META[p].label }))]}
            onValueChange={(v) => set({ provider: v === ALL ? null : v, page: null })}
          />
          <SimpleSelect
            size="sm"
            className="w-36"
            aria-label="État"
            value={enabledParam ?? ALL}
            options={[
              { value: ALL, label: "Tous" },
              { value: "true", label: "Activés" },
              { value: "false", label: "Désactivés" },
            ]}
            onValueChange={(v) => set({ enabled: v === ALL ? null : v, page: null })}
          />
          <label className="ml-auto flex items-center gap-2 text-[13px] text-muted-foreground">
            <Switch size="sm" checked={allVersions} onCheckedChange={(c) => set({ versions: c ? "all" : null, page: null })} />
            Toutes les versions
          </label>
        </div>
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} variant="plain" />
        ) : query.isPending ? (
          <TableSkeleton />
        ) : items.length === 0 && !search.applied && !provider && enabledParam === null ? (
          <EmptyState variant="plain" icon={<Gavel />} title="Aucun juge" description="Créez un premier juge pour évaluer les runs." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Juge</TableHead>
                <TableHead>Fournisseur · modèle</TableHead>
                <TableHead className="hidden lg:table-cell">Critères</TableHead>
                <TableHead className="text-right">Poids</TableHead>
                <TableHead className="hidden md:table-cell">Calibration</TableHead>
                <TableHead>Activé</TableHead>
                <TableHead className="hidden xl:table-cell">Créé</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 ? (
                <TableEmptyRow colSpan={7}>Aucun juge ne correspond à ces filtres.</TableEmptyRow>
              ) : (
                items.map((j) => {
                  const cal = calByKey.get(j.key);
                  return (
                    <TableRow
                      key={j.id}
                      interactive
                      tabIndex={0}
                      onClick={() => router.push(`/judges/${j.id}`)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") router.push(`/judges/${j.id}`);
                      }}
                    >
                      <TableCell>
                        <div className="grid gap-0.5">
                          <span className="flex items-center gap-2">
                            <Link href={`/judges/${j.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                              {j.name}
                            </Link>
                            <Badge variant="outline">v{j.version}</Badge>
                            {!j.is_latest ? <Badge tone="neutral">Ancienne version</Badge> : null}
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">{j.key}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="grid gap-1">
                          <JudgeProviderBadge value={j.provider} />
                          <span className="text-xs text-muted-foreground">
                            {j.model}
                            {j.model_version ? ` (${j.model_version})` : ""}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="hidden lg:table-cell">
                        {j.criteria.length ? (
                          <SimpleTooltip content={j.criteria.join(", ")}>
                            <span tabIndex={0} className="text-[13px]">
                              {j.criteria.length} critère(s)
                            </span>
                          </SimpleTooltip>
                        ) : (
                          <span className="text-xs text-muted-foreground">Tous les critères jugés</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{formatNumber(j.weight)}</TableCell>
                      <TableCell className="hidden md:table-cell">
                        {cal ? (
                          <SimpleTooltip content={`${cal.n} paires · kappa ${formatNumber(cal.kappa)} · accord ${formatNumber(cal.agreement_rate)}`}>
                            <span tabIndex={0}>
                              <CalibrationStatusBadge value={cal.status} />
                            </span>
                          </SimpleTooltip>
                        ) : (
                          <CalibrationStatusBadge value="insufficient_data" />
                        )}
                      </TableCell>
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <Switch
                          size="sm"
                          checked={j.enabled}
                          disabled={!canEdit || update.isPending}
                          aria-label={j.enabled ? `Désactiver ${j.name}` : `Activer ${j.name}`}
                          onCheckedChange={(enabled) =>
                            update.mutate(
                              { id: j.id, body: { enabled } },
                              {
                                onSuccess: () => toast.success(enabled ? `${j.name} activé` : `${j.name} désactivé`),
                                onError: (e) => toast.error(errorMessage(e)),
                              },
                            )
                          }
                        />
                      </TableCell>
                      <TableCell className="hidden xl:table-cell">
                        <RelativeTime date={j.created_at} className="text-xs text-muted-foreground" />
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        )}
        {query.data && query.data.total > PAGE_SIZE ? (
          <div className="border-t border-border p-3">
            <Pagination page={page} pageSize={PAGE_SIZE} total={query.data.total} onPageChange={(p) => set({ page: p > 1 ? p : null })} />
          </div>
        ) : null}
      </Card>
    </>
  );
}
