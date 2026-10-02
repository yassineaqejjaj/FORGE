"use client";

import * as React from "react";
import { ArrowLeftRight, GitCompareArrows } from "lucide-react";

import { useBreadcrumbLabel } from "@/components/layout/shell-context";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { PageHeader } from "@/components/ui/page-header";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useAgent, useAgentVersionDiff, useAgentVersions } from "@/lib/api/agents";
import { formatDate } from "@/lib/format";

import { useUrlState } from "./kit/use-url-state";
import { VersionDiffView } from "./version-diff";

/** Compare two versions of an agent (`GET /agent-versions/{to}/diff?against={from}`), selection in the URL. */
export function CompareView({ agentId }: { agentId: string }) {
  const agent = useAgent(agentId);
  const versions = useAgentVersions(agentId);
  const url = useUrlState();
  useBreadcrumbLabel(agentId, agent.data?.name);
  useBreadcrumbLabel("compare", "Comparaison");

  const list = React.useMemo(() => versions.data ?? [], [versions.data]);
  const to = url.get("to") || list[0]?.id || "";
  const toIndex = list.findIndex((v) => v.id === to);
  const from = url.get("from") || list[toIndex + 1]?.id || list.find((v) => v.id !== to)?.id || "";
  const diff = useAgentVersionDiff(to || undefined, from || undefined);

  const options = list.map((v) => ({
    value: v.id,
    label: `v${v.version}`,
    description: `${formatDate(v.created_at)}${v.changelog ? ` · ${v.changelog.slice(0, 60)}` : ""}`,
  }));

  return (
    <>
      <PageHeader
        eyebrow={agent.data?.name ?? "Agent"}
        title="Comparer deux versions"
        icon={<GitCompareArrows />}
        description="Différences de configuration champ par champ, outils et diff unifié du prompt système."
      />
      <Card className="mb-4">
        <CardContent className="grid gap-3 pt-5 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-end">
          {versions.isPending ? (
            <>
              <Skeleton className="h-9 w-full" />
              <span />
              <Skeleton className="h-9 w-full" />
            </>
          ) : (
            <>
              <Field id="cmp-from" label="Version de référence">
                <SimpleSelect id="cmp-from" value={from || undefined} onValueChange={(v) => url.set({ from: v, to })} options={options} />
              </Field>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Inverser les versions"
                onClick={() => url.set({ from: to, to: from })}
                disabled={!from || !to}
              >
                <ArrowLeftRight aria-hidden />
              </Button>
              <Field id="cmp-to" label="Version comparée">
                <SimpleSelect id="cmp-to" value={to || undefined} onValueChange={(v) => url.set({ to: v, from })} options={options} />
              </Field>
            </>
          )}
        </CardContent>
      </Card>

      {versions.isError ? (
        <ErrorState error={versions.error} onRetry={() => void versions.refetch()} />
      ) : !versions.isPending && list.length < 2 ? (
        <EmptyState icon={<GitCompareArrows />} title="Une seule version" description="Créez une deuxième version de cet agent pour pouvoir les comparer." />
      ) : from && to && from === to ? (
        <EmptyState size="sm" icon={<GitCompareArrows />} title="Choisissez deux versions différentes" />
      ) : diff.isPending ? (
        <div className="grid gap-3">
          <Skeleton className="h-40 w-full rounded-xl" />
          <Skeleton className="h-64 w-full rounded-xl" />
        </div>
      ) : diff.isError ? (
        <ErrorState error={diff.error} onRetry={() => void diff.refetch()} />
      ) : diff.data ? (
        <VersionDiffView diff={diff.data} />
      ) : null}
    </>
  );
}
