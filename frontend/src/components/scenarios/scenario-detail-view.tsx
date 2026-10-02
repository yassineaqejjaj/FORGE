"use client";

import * as React from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Archive, ArchiveRestore, Download, FilePlus2, GitFork, Pencil, Play, ScrollText, Sparkles } from "lucide-react";

import { RoleButton } from "@/components/agents/kit/role-button";
import { useUrlState } from "@/components/agents/kit/use-url-state";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { ClassificationBanner } from "@/components/domain/classification-banner";
import { DifficultyBadge } from "@/components/domain/enum-badge";
import { CostDisplay, DurationDisplay } from "@/components/domain/metric-display";
import { RelativeTime } from "@/components/domain/relative-time";
import { ScoreBadge } from "@/components/domain/score-badge";
import { RunStatusBadge } from "@/components/domain/status-badge";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
import { useBreadcrumbLabel } from "@/components/layout/shell-context";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useRunsList } from "@/lib/api/agents";
import { errorMessage } from "@/lib/api/client";
import { useScenario, useUpdateScenario, type ScenarioDetail } from "@/lib/api/scenarios";
import { formatDate, formatDateTime } from "@/lib/format";

import { DetailList, Empty } from "@/components/agents/kit/detail-list";
import { ExportScenariosDialog } from "./import-export-dialogs";
import { ScenarioContent } from "./scenario-content";
import { ScenarioMetaDialog, VariantDialog } from "./scenario-dialogs";
import { ScenarioVersionsTab } from "./scenario-versions-tab";

const TABS = ["content", "versions", "variants", "runs"] as const;
type Tab = (typeof TABS)[number];

/** Scenario detail: metadata, content, versions, variants and runs (redaction decided by the API). */
export function ScenarioDetailView({ scenarioId }: { scenarioId: string }) {
  const query = useScenario(scenarioId);
  const url = useUrlState();
  const { hasRole } = useCurrentUser();
  const update = useUpdateScenario(scenarioId);
  const [editOpen, setEditOpen] = React.useState(false);
  const [variantOpen, setVariantOpen] = React.useState(false);
  const [archiveOpen, setArchiveOpen] = React.useState(false);
  const [exportOpen, setExportOpen] = React.useState(false);
  const raw = url.get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(raw) ? (raw as Tab) : "content";
  useBreadcrumbLabel(scenarioId, query.data?.name);

  if (query.isPending) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-16 w-full max-w-2xl" />
        <Skeleton className="h-10 w-full max-w-md" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const s = query.data;
  const latest = s.latest;
  const isPrivate = s.visibility === "private";
  const redacted = Boolean(latest?.redacted);
  const contentReason = redacted || (isPrivate && !hasRole("maintainer")) ? "Le contenu des scénarios privés est réservé aux mainteneurs." : null;
  const metaReason = isPrivate && !hasRole("maintainer") ? "Les scénarios privés sont gérés par les mainteneurs." : null;

  return (
    <>
      <PageHeader
        eyebrow={s.category_label}
        title={s.name}
        icon={<ScrollText />}
        meta={
          <>
            <VisibilityBadge visibility={s.visibility} />
            <ClassificationBadge level={s.classification} />
            {s.difficulty ? <DifficultyBadge value={s.difficulty} withTooltip={false} /> : null}
            {s.variant_label ? (
              <Badge tone="violet" icon={<GitFork aria-hidden />}>
                {s.variant_label}
              </Badge>
            ) : null}
            {s.archived ? (
              <Badge tone="neutral" icon={<Archive aria-hidden />}>
                Archivé
              </Badge>
            ) : null}
          </>
        }
        actions={
          <>
            <RoleButton minRole="editor" variant="secondary" leftIcon={<Pencil aria-hidden />} onClick={() => setEditOpen(true)} disabledReason={metaReason}>
              Modifier
            </RoleButton>
            <RoleButton minRole="editor" variant="secondary" leftIcon={<GitFork aria-hidden />} onClick={() => setVariantOpen(true)} disabledReason={contentReason}>
              Variante
            </RoleButton>
            <Button variant="secondary" leftIcon={<Download aria-hidden />} onClick={() => setExportOpen(true)}>
              Exporter
            </Button>
            <RoleButton
              minRole="editor"
              variant="secondary"
              leftIcon={s.archived ? <ArchiveRestore aria-hidden /> : <Archive aria-hidden />}
              onClick={() => setArchiveOpen(true)}
              disabledReason={metaReason}
            >
              {s.archived ? "Désarchiver" : "Archiver"}
            </RoleButton>
            <RoleButton minRole="editor" href={`/scenarios/${s.id}/versions/new`} leftIcon={<FilePlus2 aria-hidden />} disabledReason={contentReason}>
              Nouvelle version
            </RoleButton>
          </>
        }
      >
        <DetailList
          columns={3}
          className="rounded-xl border border-border bg-card p-4 lg:grid-cols-6"
          items={[
            { label: "Identifiant", value: <span className="font-mono text-xs">{s.slug}</span> },
            { label: "Dernière version", value: `v${s.latest_version}` },
            {
              label: "Fresh jusqu'au",
              value:
                s.visibility === "fresh" && s.fresh_until ? (
                  <span className="flex items-center gap-1">
                    <Sparkles className={s.is_fresh ? "size-3.5 text-teal-600 dark:text-teal-400" : "size-3.5 text-subtle-foreground"} aria-hidden />
                    {formatDate(s.fresh_until)}
                    {!s.is_fresh ? <span className="text-xs text-muted-foreground">(expiré)</span> : null}
                  </span>
                ) : (
                  <Empty />
                ),
            },
            {
              label: "Étiquettes",
              value: s.tags.length ? (
                <span className="flex flex-wrap gap-1">
                  {s.tags.map((t) => (
                    <Badge key={t}>{t}</Badge>
                  ))}
                </span>
              ) : (
                <Empty />
              ),
            },
            { label: "Créé", value: formatDateTime(s.created_at) },
            { label: "Modifié", value: <RelativeTime date={s.updated_at} /> },
          ]}
        />
      </PageHeader>

      <ClassificationBanner level={s.classification} context="scenario" className="mb-4" />
      {s.archived ? (
        <Alert tone="neutral" title="Scénario archivé" className="mb-4">
          Il n&apos;apparaît plus dans la bibliothèque par défaut ni dans les nouvelles sélections. Ses versions et ses runs restent consultables.
        </Alert>
      ) : null}

      <Tabs value={tab} onValueChange={(t) => url.set({ tab: t === "content" ? null : t, version: null, view: null, a: null, b: null })}>
        <TabsList>
          <TabsTrigger value="content">Contenu</TabsTrigger>
          <TabsTrigger value="versions" count={s.versions.length}>
            Versions
          </TabsTrigger>
          <TabsTrigger value="variants" count={s.family.length || undefined}>
            Variantes
          </TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
        </TabsList>
        <TabsContent value="content">
          {latest ? (
            <ScenarioContent version={latest} />
          ) : (
            <EmptyState icon={<ScrollText />} title="Aucune version" description="Ce scénario n'a pas encore de contenu." />
          )}
        </TabsContent>
        <TabsContent value="versions">
          <ScenarioVersionsTab scenario={s} />
        </TabsContent>
        <TabsContent value="variants">
          <VariantsTab scenario={s} onCreate={() => setVariantOpen(true)} contentReason={contentReason} />
        </TabsContent>
        <TabsContent value="runs">
          <ScenarioRuns scenarioId={s.id} />
        </TabsContent>
      </Tabs>

      <ScenarioMetaDialog open={editOpen} onOpenChange={setEditOpen} scenario={s} />
      <VariantDialog open={variantOpen} onOpenChange={setVariantOpen} scenario={s} />
      <ExportScenariosDialog
        open={exportOpen}
        onOpenChange={setExportOpen}
        params={{ ids: [s.id], archived: s.archived }}
        scopeLabel={`Scénario « ${s.name} »`}
        maxClassification={s.classification}
      />
      <ConfirmDialog
        open={archiveOpen}
        onOpenChange={setArchiveOpen}
        title={s.archived ? "Désarchiver ce scénario ?" : "Archiver ce scénario ?"}
        description={
          s.archived
            ? "Le scénario réapparaîtra dans la bibliothèque."
            : "Le scénario sera masqué de la bibliothèque et des nouvelles sélections. Les benchmarks existants, ses versions et ses runs restent consultables."
        }
        confirmLabel={s.archived ? "Désarchiver" : "Archiver"}
        destructive={!s.archived}
        onConfirm={() =>
          update.mutateAsync({ archived: !s.archived }).then(
            () => {
              toast.success(s.archived ? "Scénario désarchivé" : "Scénario archivé");
              setArchiveOpen(false);
            },
            (e: unknown) => toast.error(errorMessage(e)),
          )
        }
      />
    </>
  );
}

function VariantsTab({ scenario, onCreate, contentReason }: { scenario: ScenarioDetail; onCreate: () => void; contentReason: string | null }) {
  const members = scenario.family;
  return (
    <Card>
      <CardHeader className="flex-row items-start">
        <div className="grid gap-1">
          <CardTitle>Famille de variantes</CardTitle>
          <CardDescription>Variantes d&apos;un même cas : la robustesse d&apos;un agent est mesurée sur la famille entière.</CardDescription>
        </div>
        <CardAction>
          <RoleButton minRole="editor" size="sm" leftIcon={<GitFork aria-hidden />} onClick={onCreate} disabledReason={contentReason}>
            Nouvelle variante
          </RoleButton>
        </CardAction>
      </CardHeader>
      <CardContent>
        {members.length === 0 ? (
          <EmptyState
            size="sm"
            icon={<GitFork />}
            title="Aucune variante"
            description="Créez des variantes (contexte réduit, formulation adverse, contraintes différentes…) pour mesurer la robustesse."
          />
        ) : (
          <ul className="grid gap-2">
            {members.map((m) => {
              const current = m.id === scenario.id;
              const original = !m.parent_scenario_id;
              return (
                <li key={m.id}>
                  <Link
                    href={`/scenarios/${m.id}`}
                    aria-current={current ? "page" : undefined}
                    className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2.5 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:border-brand/50 aria-[current=page]:bg-brand-soft/40"
                  >
                    <span className="text-[13px] font-medium">{m.name}</span>
                    <span className="font-mono text-[11.5px] text-muted-foreground">{m.slug}</span>
                    {original ? <Badge tone="neutral">Original</Badge> : null}
                    {m.variant_label ? (
                      <Badge tone="violet" icon={<GitFork aria-hidden />}>
                        {m.variant_label}
                      </Badge>
                    ) : null}
                    <VisibilityBadge visibility={m.visibility} noTooltip />
                    {current ? <span className="ml-auto text-xs text-muted-foreground">Scénario affiché</span> : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
        {members.length ? (
          <p className="mt-3 text-xs text-muted-foreground">
            <Link href={`/scenarios?family=${scenario.family_id}`} className="font-medium text-primary hover:underline">
              Voir la famille dans la bibliothèque
            </Link>
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ScenarioRuns({ scenarioId }: { scenarioId: string }) {
  const runs = useRunsList({ scenario_id: scenarioId, page_size: 20 });
  return (
    <Card>
      <CardHeader className="flex-row items-start">
        <div className="grid gap-1">
          <CardTitle>Runs récents</CardTitle>
          <CardDescription>{runs.data ? `${runs.data.total} run${runs.data.total > 1 ? "s" : ""} au total, 20 plus récents affichés` : "Runs sur ce scénario"}</CardDescription>
        </div>
        <CardAction>
          <Button asChild variant="secondary" size="sm">
            <Link href={`/runs?scenario_id=${scenarioId}`}>Voir dans les runs</Link>
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
          <EmptyState variant="plain" size="sm" icon={<Play />} title="Aucun run" description="Aucun agent n'a encore été exécuté sur ce scénario." className="pb-8" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Agent</TableHead>
                <TableHead>Version du scénario</TableHead>
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
                      {r.agent_label ?? r.agent_name ?? "—"}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{r.scenario_version ? `v${r.scenario_version}` : "—"}</TableCell>
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
