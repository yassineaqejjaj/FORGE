"use client";

import * as React from "react";
import Link from "next/link";
import { CopyPlus, GitCompareArrows, Hash, Play, TriangleAlert } from "lucide-react";

import { useBreadcrumbLabel } from "@/components/layout/shell-context";
import { AdapterKindBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { ScoreBadge } from "@/components/domain/score-badge";
import { RunStatusBadge } from "@/components/domain/status-badge";
import { CostDisplay, DurationDisplay } from "@/components/domain/metric-display";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/code-block";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAgentVersion, useAgentVersions, useRunsList } from "@/lib/api/agents";
import { formatDateTime, plural } from "@/lib/format";

import { AgentTestPanel } from "./agent-test-panel";
import { RoleButton } from "./kit/role-button";
import { useUrlState } from "./kit/use-url-state";
import { shortHash } from "./labels";
import { VersionConfig } from "./version-config";

const TABS = ["config", "test", "runs"] as const;
type Tab = (typeof TABS)[number];

/** Full configuration of one immutable agent version, its test panel and its runs. */
export function VersionDetailView({ agentId, versionId }: { agentId: string; versionId: string }) {
  const version = useAgentVersion(versionId);
  const versions = useAgentVersions(agentId);
  const url = useUrlState();
  const rawTab = url.get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(rawTab) ? (rawTab as Tab) : "config";
  const v = version.data;
  useBreadcrumbLabel(agentId, v?.agent_name);
  useBreadcrumbLabel("versions", "Versions");
  useBreadcrumbLabel(versionId, v ? `v${v.version}` : undefined);

  if (version.isPending) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-16 w-full max-w-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }
  if (version.isError) return <ErrorState error={version.error} onRetry={() => void version.refetch()} />;
  if (!v) return null;

  const list = versions.data ?? [];
  const index = list.findIndex((x) => x.id === v.id);
  const previous = index >= 0 ? list[index + 1] : undefined;
  const latest = list[0]?.id === v.id;

  return (
    <>
      <PageHeader
        eyebrow={
          <Link href={`/agents/${agentId}`} className="hover:underline">
            {v.agent_name}
          </Link>
        }
        title={`Version ${v.version}`}
        description={v.changelog || undefined}
        meta={
          <>
            <AdapterKindBadge value={v.adapter_kind} />
            {latest ? (
              <Badge tone="orange" dot>
                Dernière
              </Badge>
            ) : null}
            {v.contamination.length ? (
              <Badge tone="amber" icon={<TriangleAlert aria-hidden />}>
                {plural(v.contamination.length, "alerte")} de contamination
              </Badge>
            ) : null}
          </>
        }
        actions={
          <>
            {previous ? (
              <Button asChild variant="secondary">
                <Link href={`/agents/${agentId}/compare?from=${previous.id}&to=${v.id}`}>
                  <GitCompareArrows aria-hidden /> Comparer à v{previous.version}
                </Link>
              </Button>
            ) : null}
            <RoleButton minRole="editor" variant="secondary" leftIcon={<Play aria-hidden />} onClick={() => url.set({ tab: "test" })}>
              Tester
            </RoleButton>
            <RoleButton minRole="editor" href={`/agents/${agentId}/versions/new?base=${v.id}`} leftIcon={<CopyPlus aria-hidden />}>
              Nouvelle version basée sur celle-ci
            </RoleButton>
          </>
        }
      >
        <dl className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <dt>Créée</dt>
            <dd className="text-foreground">{formatDateTime(v.created_at)}</dd>
          </div>
          <div className="flex items-center gap-1.5">
            <dt className="flex items-center gap-1">
              <Hash className="size-3.5" aria-hidden /> Empreinte
            </dt>
            <dd className="flex items-center gap-1 font-mono text-foreground" title={v.content_hash}>
              {shortHash(v.content_hash, 16)}
              <CopyButton value={v.content_hash} label="Copier l'empreinte" className="size-6" />
            </dd>
          </div>
          <div className="flex items-center gap-1.5">
            <dt>Modèle</dt>
            <dd className="font-mono text-foreground">{v.model_configuration?.model ?? "—"}</dd>
          </div>
        </dl>
      </PageHeader>

      <Tabs value={tab} onValueChange={(t) => url.set({ tab: t === "config" ? null : t })}>
        <TabsList>
          <TabsTrigger value="config">Configuration</TabsTrigger>
          <TabsTrigger value="test">Tester l&apos;agent</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
        </TabsList>
        <TabsContent value="config">
          <VersionConfig version={v} />
        </TabsContent>
        <TabsContent value="test">
          <AgentTestPanel versionId={v.id} />
        </TabsContent>
        <TabsContent value="runs">
          <VersionRuns versionId={v.id} />
        </TabsContent>
      </Tabs>
    </>
  );
}

function VersionRuns({ versionId }: { versionId: string }) {
  const runs = useRunsList({ agent_version_id: versionId, page_size: 20 });
  return (
    <Card>
      <CardHeader className="flex-row items-start">
        <div className="grid gap-1">
          <CardTitle>Runs de cette version</CardTitle>
          <CardDescription>
            {runs.data ? `${plural(runs.data.total, "run")} au total, 20 plus récents affichés` : "Runs les plus récents"}
          </CardDescription>
        </div>
        <CardAction>
          <Button asChild variant="secondary" size="sm">
            <Link href={`/runs?agent_version_id=${versionId}`}>Voir dans les runs</Link>
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="px-0 pb-0">
        {runs.isError ? (
          <ErrorState error={runs.error} onRetry={() => void runs.refetch()} variant="plain" size="sm" />
        ) : runs.isPending ? (
          <div className="grid gap-2 p-5 pt-0">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : !runs.data.items.length ? (
          <EmptyState variant="plain" size="sm" icon={<Play />} title="Aucun run" description="Cette version n'a pas encore été exécutée." className="pb-8" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Scénario</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead>Composite</TableHead>
                <TableHead className="text-right">Latence</TableHead>
                <TableHead className="text-right">Coût</TableHead>
                <TableHead>Créé</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.data.items.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>
                    <Link href={`/runs/${r.id}`} className="font-medium hover:underline">
                      {r.scenario_name}
                    </Link>
                    {r.scenario_version ? <span className="ml-1.5 text-xs text-muted-foreground">v{r.scenario_version}</span> : null}
                  </TableCell>
                  <TableCell>
                    <RunStatusBadge status={r.status} detail={r.status_detail} />
                  </TableCell>
                  <TableCell>
                    <ScoreBadge value={r.composite_score} passed={r.passed} gateFailed={r.gate_failed} />
                  </TableCell>
                  <TableCell className="text-right">
                    <DurationDisplay ms={r.latency_ms} muted />
                  </TableCell>
                  <TableCell className="text-right">
                    <CostDisplay value={r.cost} muted />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    <RelativeTime date={r.created_at} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
