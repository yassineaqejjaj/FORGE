"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, Search, SlidersHorizontal } from "lucide-react";

import { RequireRole } from "@/components/auth/require-role";
import { TableSkeleton } from "@/components/benchmarks/common";
import { pageFrom, useUrlSearch, useUrlState } from "@/components/benchmarks/use-url-state";
import { AggregationMethodBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { JudgesAreaTabs } from "@/components/layout/area-tabs";
import { useEvaluationConfigs } from "@/lib/api/evaluation-configs";
import { formatNumber } from "@/lib/format";
import { WeightsBar } from "./config-helpers";

const PAGE_SIZE = 25;

export function ConfigsListView() {
  const router = useRouter();
  const { get, set } = useUrlState();
  const search = useUrlSearch("q");
  const page = pageFrom(get("page"));
  const allVersions = get("versions") === "all";
  const query = useEvaluationConfigs({ page, page_size: PAGE_SIZE, q: search.applied || undefined, latest_only: !allVersions });
  const items = query.data?.items ?? [];

  return (
    <>
      <PageHeader
        eyebrow="Configuration · Juges"
        title="Configurations de score"
        icon={<SlidersHorizontal />}
        description="Pondérations des dimensions et critères, normalisation des coûts et latences, garde-fous, juges épinglés, agrégation multi-juges et seuil de réussite. Chaque version est immuable."
        actions={
          <RequireRole min="maintainer">
            <Button asChild>
              <Link href="/evaluation-configs/new">
                <Plus aria-hidden /> Nouvelle configuration
              </Link>
            </Button>
          </RequireRole>
        }
      >
        <JudgesAreaTabs />
      </PageHeader>
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <Input
            size="sm"
            leftIcon={<Search aria-hidden />}
            placeholder="Rechercher une configuration…"
            value={search.value}
            onChange={(e) => search.setValue(e.target.value)}
            className="w-full sm:w-72"
            aria-label="Rechercher une configuration"
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
        ) : items.length === 0 && !search.applied ? (
          <EmptyState variant="plain" icon={<SlidersHorizontal />} title="Aucune configuration" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Configuration</TableHead>
                <TableHead className="hidden w-[34%] lg:table-cell">Pondérations</TableHead>
                <TableHead className="text-right">Seuil</TableHead>
                <TableHead className="hidden md:table-cell">Garde-fous · juges</TableHead>
                <TableHead className="hidden md:table-cell">Agrégation</TableHead>
                <TableHead className="hidden xl:table-cell">Créée</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 ? (
                <TableEmptyRow colSpan={6}>Aucune configuration ne correspond.</TableEmptyRow>
              ) : (
                items.map((c) => (
                  <TableRow
                    key={c.id}
                    interactive
                    tabIndex={0}
                    onClick={() => router.push(`/evaluation-configs/${c.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") router.push(`/evaluation-configs/${c.id}`);
                    }}
                  >
                    <TableCell>
                      <div className="grid gap-0.5">
                        <span className="flex flex-wrap items-center gap-1.5">
                          <Link href={`/evaluation-configs/${c.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                            {c.name}
                          </Link>
                          <Badge variant="outline">v{c.version}</Badge>
                          {c.is_default ? <Badge tone="orange">Par défaut</Badge> : null}
                          {!c.is_latest ? <Badge tone="neutral">Ancienne version</Badge> : null}
                        </span>
                        <span className="font-mono text-xs text-muted-foreground">{c.key}</span>
                      </div>
                    </TableCell>
                    <TableCell className="hidden lg:table-cell">
                      <WeightsBar weights={c.dimension_weights} className="[&_ul]:hidden" />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(c.pass_threshold, 0)}</TableCell>
                    <TableCell className="hidden text-[13px] md:table-cell">
                      {c.gates.length} garde-fou(s) · {c.judge_ids.length} juge(s)
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <AggregationMethodBadge value={String(c.aggregation.method ?? "mean")} />
                    </TableCell>
                    <TableCell className="hidden xl:table-cell">
                      <RelativeTime date={c.created_at} className="text-xs text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                ))
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
