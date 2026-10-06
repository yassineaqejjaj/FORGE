"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, ClipboardCheck, EyeOff, Inbox, Info, Scale, ShieldQuestion } from "lucide-react";

import { RoleGate } from "@/components/auth/require-role";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { RunOriginBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { ScoreBadge } from "@/components/domain/score-badge";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
import { FilterBar, FilterField, FilterSelect } from "@/components/runs/filter-controls";
import { useSearchState } from "@/components/runs/use-search-state";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { DEFAULT_PAGE_SIZE } from "@/lib/api/types";
import { useGoldDatasets, useReviewQueue, type ReviewQueueItem } from "@/lib/api/reviews";
import { formatNumber, formatScore } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Threshold below which the aggregated judge confidence is flagged in the queue (display only). */
const LOW_CONFIDENCE = 0.5;

function PriorityReasons({ item }: { item: ReviewQueueItem }) {
  const reasons: React.ReactNode[] = [];
  if (typeof item.max_spread === "number" && item.max_spread > 0) {
    reasons.push(
      <SimpleTooltip key="spread" content="Écart maximal entre les verdicts des juges sur un critère (max − min, échelle 0–1).">
        <span className="inline-flex">
          <Badge tone={item.max_spread >= 0.3 ? "red" : "amber"} icon={<Scale aria-hidden />}>
            Désaccord des juges {formatScore(item.max_spread)}
          </Badge>
        </span>
      </SimpleTooltip>,
    );
  }
  if (typeof item.min_confidence === "number" && item.min_confidence < LOW_CONFIDENCE) {
    reasons.push(
      <SimpleTooltip key="conf" content="Confiance agrégée la plus faible parmi les critères jugés.">
        <span className="inline-flex">
          <Badge tone="violet" icon={<ShieldQuestion aria-hidden />}>
            Confiance faible {formatScore(item.min_confidence)}
          </Badge>
        </span>
      </SimpleTooltip>,
    );
  }
  if (!reasons.length) return <span className="text-xs text-muted-foreground">Jamais évalué par vous</span>;
  return <div className="flex flex-wrap gap-1">{reasons}</div>;
}

/** `/reviews` — human review queue (evaluator+), ordered by judge disagreement then low confidence. */
export function ReviewQueueView() {
  const search = useSearchState();
  const blind = search.get("blind") !== "0";
  const datasetId = search.get("dataset");
  const page = Math.max(1, search.getNumber("page") ?? 1);
  const datasets = useGoldDatasets();
  const queue = useReviewQueue({ page, page_size: DEFAULT_PAGE_SIZE, dataset_id: datasetId, blind });
  const items = queue.data?.items ?? [];

  const workspaceHref = (runId: string) => {
    const qs = new URLSearchParams();
    if (!blind) qs.set("blind", "0");
    if (datasetId) qs.set("dataset", datasetId);
    const s = qs.toString();
    return `/reviews/${runId}${s ? `?${s}` : ""}`;
  };

  return (
    <RoleGate min="evaluator">
      <PageHeader
        eyebrow="Améliorer"
        title="Revue humaine"
        icon={<ClipboardCheck />}
        description="Notez les runs où les juges IA sont le moins fiables : vos évaluations calibrent les juges et peuvent remplacer les scores IA."
        meta={queue.data ? <Badge tone="orange">{formatNumber(queue.data.total, 0)} à évaluer</Badge> : null}
        actions={
          items[0] ? (
            <Button asChild rightIcon={<ArrowRight aria-hidden />}>
              <Link href={workspaceHref(items[0].run_id)}>Commencer la revue</Link>
            </Button>
          ) : null
        }
      />

      <FilterBar activeCount={search.countActive(["dataset"])} onReset={() => search.clear(["blind"])} className="mb-4">
        <FilterSelect
          id="reviews-dataset"
          label="Jeu de données gold"
          value={datasetId}
          onChange={(dataset) => search.set({ dataset })}
          options={(datasets.data?.items ?? []).map((d) => ({ value: d.id, label: d.name, description: `${d.items_count} runs` }))}
          allLabel="Tous les runs terminés"
          loading={datasets.isPending}
          className="col-span-2"
        />
        <FilterField label="Mode aveugle" htmlFor="reviews-blind" className="col-span-2">
          <div className="flex h-8 items-center gap-2">
            <Switch id="reviews-blind" checked={blind} onCheckedChange={(v) => search.set({ blind: v ? undefined : "0" })} />
            <Label htmlFor="reviews-blind" className="flex items-center gap-1.5 text-[13px] font-normal text-muted-foreground">
              <EyeOff className="size-3.5" aria-hidden />
              {blind ? "Scores IA masqués jusqu'à votre évaluation" : "Scores IA visibles"}
            </Label>
          </div>
        </FilterField>
      </FilterBar>

      <Alert tone="blue" icon={<Info aria-hidden />} className="mb-4" title="Comment la file est ordonnée">
        Apprentissage actif : les runs terminés que vous n&apos;avez pas encore notés, triés par désaccord maximal entre juges, puis par
        confiance la plus faible, puis du plus récent au plus ancien. Les scénarios privés sont réservés aux mainteneurs.
      </Alert>

      {queue.isError && !queue.data ? (
        <ErrorState error={queue.error} onRetry={() => void queue.refetch()} />
      ) : !queue.isPending && items.length === 0 ? (
        <EmptyState
          icon={<Inbox />}
          title="File de revue vide"
          description={datasetId ? "Vous avez noté tous les runs de ce jeu de données gold." : "Vous avez noté tous les runs terminés qui vous sont accessibles. Merci !"}
        />
      ) : (
        <div className={cn("grid gap-3", queue.isPlaceholderData && "opacity-60")}>
          <Table dense containerClassName="rounded-xl border border-border bg-card shadow-panel">
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                <TableHead>Scénario</TableHead>
                <TableHead>Version d&apos;agent</TableHead>
                <TableHead>Priorité</TableHead>
                <TableHead>Score IA</TableHead>
                <TableHead>Critères</TableHead>
                <TableHead>Créé</TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {queue.isPending
                ? Array.from({ length: 6 }, (_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: 8 }, (__, j) => (
                        <TableCell key={j}>
                          <Skeleton className="h-4 w-20" />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                : items.map((item, i) => (
                    <TableRow key={item.run_id}>
                      <TableCell className="tabular-nums text-muted-foreground">{(page - 1) * DEFAULT_PAGE_SIZE + i + 1}</TableCell>
                      <TableCell className="max-w-[18rem]">
                        <div className="flex min-w-0 items-center gap-2">
                          <VisibilityBadge visibility={item.visibility} iconOnly noTooltip />
                          <div className="grid min-w-0">
                            <span className="truncate font-medium">{item.scenario_name}</span>
                            <span className="truncate font-mono text-[11px] text-muted-foreground">{item.scenario_slug}</span>
                          </div>
                          {item.classification >= 2 ? <ClassificationBadge level={item.classification} showLabel={false} /> : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="grid gap-0.5">
                          <span className="truncate">{item.agent_label ?? "—"}</span>
                          <RunOriginBadge value={item.origin} />
                        </div>
                      </TableCell>
                      <TableCell>
                        <PriorityReasons item={item} />
                      </TableCell>
                      <TableCell>
                        {item.blind ? (
                          <Badge tone="neutral" variant="outline" icon={<EyeOff aria-hidden />}>
                            Masqué
                          </Badge>
                        ) : (
                          <ScoreBadge value={item.composite_score} />
                        )}
                      </TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">{item.criteria.length}</TableCell>
                      <TableCell className="text-muted-foreground">
                        <RelativeTime date={item.created_at} />
                      </TableCell>
                      <TableCell className="text-right">
                        <Button asChild size="xs" variant={i === 0 && page === 1 ? "primary" : "secondary"}>
                          <Link href={workspaceHref(item.run_id)}>Évaluer</Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
          {queue.data ? (
            <Pagination page={page} pageSize={queue.data.page_size} total={queue.data.total} onPageChange={(p) => search.set({ page: p > 1 ? p : undefined })} />
          ) : null}
        </div>
      )}
    </RoleGate>
  );
}
