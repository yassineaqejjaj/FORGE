"use client";

import * as React from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Archive, ArchiveRestore, Bot, GitBranchPlus, GitCompareArrows, History, Pencil, Play } from "lucide-react";

import { useBreadcrumbLabel } from "@/components/layout/shell-context";
import { RelativeTime } from "@/components/domain/relative-time";
import { RunStatusBadge } from "@/components/domain/status-badge";
import { ScoreBadge } from "@/components/domain/score-badge";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { JsonViewer } from "@/components/ui/json-viewer";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { useAgent, useAgentVersions, useRunsList, useUpdateAgent } from "@/lib/api/agents";
import { formatDateTime } from "@/lib/format";

import { AgentFormDialog } from "./agent-form-dialog";
import { DetailList, Empty } from "./kit/detail-list";
import { RoleButton } from "./kit/role-button";
import { VersionsTimeline } from "./versions-timeline";

/** Agent detail: metadata, versions timeline, recent runs. */
export function AgentDetailView({ agentId }: { agentId: string }) {
  const agent = useAgent(agentId);
  const versions = useAgentVersions(agentId);
  const runs = useRunsList({ agent_id: agentId, page_size: 5 });
  const update = useUpdateAgent(agentId);
  const [editOpen, setEditOpen] = React.useState(false);
  const [archiveOpen, setArchiveOpen] = React.useState(false);
  useBreadcrumbLabel(agentId, agent.data?.name);

  if (agent.isPending) return <DetailSkeleton />;
  if (agent.isError) return <ErrorState error={agent.error} onRetry={() => void agent.refetch()} />;

  const a = agent.data;
  const list = versions.data ?? [];
  const latest = list[0];
  const previous = list[1];

  return (
    <>
      <PageHeader
        eyebrow="Agent"
        title={a.name}
        icon={<Bot />}
        description={a.description || undefined}
        meta={
          <>
            {a.archived ? (
              <Badge tone="neutral" icon={<Archive aria-hidden />}>
                Archivé
              </Badge>
            ) : null}
            {a.latest_version ? (
              <Badge tone="orange" variant="outline" mono>
                v{a.latest_version.version}
              </Badge>
            ) : null}
          </>
        }
        actions={
          <>
            <RoleButton minRole="editor" variant="secondary" leftIcon={<Pencil aria-hidden />} onClick={() => setEditOpen(true)}>
              Modifier
            </RoleButton>
            <RoleButton
              minRole="editor"
              variant="secondary"
              leftIcon={a.archived ? <ArchiveRestore aria-hidden /> : <Archive aria-hidden />}
              onClick={() => setArchiveOpen(true)}
            >
              {a.archived ? "Désarchiver" : "Archiver"}
            </RoleButton>
            {latest && previous ? (
              <Button asChild variant="secondary">
                <Link href={`/agents/${agentId}/compare?from=${previous.id}&to=${latest.id}`}>
                  <GitCompareArrows aria-hidden /> Comparer
                </Link>
              </Button>
            ) : null}
            <RoleButton
              minRole="editor"
              href={`/agents/${agentId}/versions/new${latest ? `?base=${latest.id}` : ""}`}
              leftIcon={<GitBranchPlus aria-hidden />}
              disabledReason={a.archived ? "Désarchivez l'agent pour créer une version." : null}
            >
              Nouvelle version
            </RoleButton>
          </>
        }
      />

      {a.archived ? (
        <Alert tone="neutral" title="Agent archivé" className="mb-4">
          Il n&apos;apparaît plus dans les listes par défaut. Ses versions et ses runs restent consultables.
        </Alert>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Card>
          <CardHeader className="flex-row items-start">
            <div className="grid gap-1">
              <CardTitle className="flex items-center gap-2">
                <History className="size-4 text-muted-foreground" aria-hidden /> Versions
              </CardTitle>
              <CardDescription>Versions immuables, de la plus récente à la plus ancienne.</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            {versions.isPending ? (
              <div className="grid gap-3">
                {Array.from({ length: 3 }, (_, i) => (
                  <Skeleton key={i} className="h-28 w-full" />
                ))}
              </div>
            ) : versions.isError ? (
              <ErrorState error={versions.error} onRetry={() => void versions.refetch()} size="sm" />
            ) : list.length === 0 ? (
              <EmptyState
                icon={<GitBranchPlus />}
                title="Aucune version"
                description="Créez la première version : adapter, modèle, prompt système, outils, contexte et budget."
                action={
                  <RoleButton minRole="editor" size="sm" href={`/agents/${agentId}/versions/new`} leftIcon={<GitBranchPlus aria-hidden />}>
                    Créer la première version
                  </RoleButton>
                }
              />
            ) : (
              <VersionsTimeline agentId={agentId} versions={list} />
            )}
          </CardContent>
        </Card>

        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Informations</CardTitle>
            </CardHeader>
            <CardContent>
              <DetailList
                columns={1}
                items={[
                  { label: "Identifiant", value: <span className="font-mono text-xs">{a.slug}</span> },
                  { label: "Fournisseur", value: a.provider || <Empty /> },
                  {
                    label: "Étiquettes",
                    value: a.tags.length ? (
                      <span className="flex flex-wrap gap-1">
                        {a.tags.map((t) => (
                          <Badge key={t}>{t}</Badge>
                        ))}
                      </span>
                    ) : (
                      <Empty />
                    ),
                  },
                  { label: "Versions", value: a.versions_count },
                  { label: "Créé", value: formatDateTime(a.created_at) },
                  { label: "Modifié", value: <RelativeTime date={a.updated_at} /> },
                  Object.keys(a.metadata).length
                    ? { label: "Métadonnées", value: <JsonViewer data={a.metadata} maxHeightClassName="max-h-48" /> }
                    : null,
                ]}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-start">
              <div className="grid gap-1">
                <CardTitle>Runs récents</CardTitle>
                <CardDescription>Toutes versions confondues</CardDescription>
              </div>
              <CardAction>
                <Link href={`/runs?agent_id=${agentId}`} className="text-[13px] font-medium text-primary hover:underline">
                  Tous les runs
                </Link>
              </CardAction>
            </CardHeader>
            <CardContent>
              {runs.isPending ? (
                <SkeletonText lines={4} />
              ) : runs.data && runs.data.items.length ? (
                <ul className="grid divide-y divide-border">
                  {runs.data.items.map((run) => (
                    <li key={run.id}>
                      <Link
                        href={`/runs/${run.id}`}
                        className="-mx-2 grid gap-1 rounded-md px-2 py-2 hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <span className="flex items-center justify-between gap-2">
                          <span className="truncate text-[13px] font-medium">{run.scenario_name}</span>
                          <ScoreBadge value={run.composite_score} passed={run.passed} gateFailed={run.gate_failed} />
                        </span>
                        <span className="flex items-center gap-2 text-xs text-muted-foreground">
                          <RunStatusBadge status={run.status} />
                          <span className="font-mono">v{run.agent_version}</span>
                          <RelativeTime date={run.created_at} />
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  size="sm"
                  variant="plain"
                  icon={<Play />}
                  title="Aucun run"
                  description="Cet agent n'a pas encore été exécuté sur un scénario."
                />
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <AgentFormDialog open={editOpen} onOpenChange={setEditOpen} agent={a} />
      <ConfirmDialog
        open={archiveOpen}
        onOpenChange={setArchiveOpen}
        title={a.archived ? "Désarchiver cet agent ?" : "Archiver cet agent ?"}
        description={
          a.archived
            ? "L'agent réapparaîtra dans la liste des agents actifs."
            : "L'agent sera masqué des listes par défaut. Ses versions, runs et résultats restent consultables et peuvent être restaurés."
        }
        confirmLabel={a.archived ? "Désarchiver" : "Archiver"}
        destructive={!a.archived}
        onConfirm={() =>
          update.mutateAsync({ archived: !a.archived }).then(
            () => {
              toast.success(a.archived ? "Agent désarchivé" : "Agent archivé");
              setArchiveOpen(false);
            },
            (e: unknown) => toast.error(e instanceof Error ? e.message : "Action impossible"),
          )
        }
      />
    </>
  );
}

function DetailSkeleton() {
  return (
    <div className="grid gap-6" aria-busy>
      <div className="flex items-start gap-3">
        <Skeleton className="size-9 rounded-lg" />
        <div className="grid gap-2">
          <Skeleton className="h-6 w-56" />
          <Skeleton className="h-4 w-80" />
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Skeleton className="h-96 w-full rounded-xl" />
        <Skeleton className="h-72 w-full rounded-xl" />
      </div>
    </div>
  );
}
