"use client";

import Link from "next/link";
import { ArrowRight, Database, FileText } from "lucide-react";

import { TableSkeleton } from "@/components/benchmarks/common";
import { RelativeTime } from "@/components/domain/relative-time";
import { useBreadcrumbLabel } from "@/components/layout/shell-context";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { DATASET_KIND_META, useDataset, type DatasetItem } from "@/lib/api/datasets";
import { shortId } from "@/lib/format";

import { DatasetKindBadge } from "./datasets-list-view";

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function ContextItem({ item }: { item: DatasetItem }) {
  const title = text(item.content.title) ?? item.key;
  const body = text(item.content.content);
  const source = text(item.content.source);
  return (
    <li className="rounded-lg border border-border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <FileText className="size-4 text-subtle-foreground" aria-hidden />
        <span className="font-medium">{title}</span>
        <span className="font-mono text-[11px] text-muted-foreground">[{item.key}]</span>
        {source ? <span className="ml-auto truncate text-[12px] text-muted-foreground">{source}</span> : null}
      </div>
      {body ? <p className="mt-2 line-clamp-4 whitespace-pre-line text-[13px] leading-relaxed text-muted-foreground">{body}</p> : null}
    </li>
  );
}

function GoldItem({ item }: { item: DatasetItem }) {
  const run = item.run ?? {};
  const label = text(run.scenario_name) ?? text(run.label) ?? `Exécution ${shortId(item.run_id ?? item.key)}`;
  const agent = text(run.agent_label);
  return (
    <li>
      {item.run_id ? (
        <Link
          href={`/runs/${item.run_id}`}
          className="flex items-center gap-3 rounded-lg border border-border p-3 transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="grid min-w-0 flex-1">
            <span className="truncate font-medium">{label}</span>
            {agent ? <span className="truncate text-[12px] text-muted-foreground">{agent}</span> : null}
          </span>
          <ArrowRight className="size-4 shrink-0 text-subtle-foreground" aria-hidden />
        </Link>
      ) : (
        <div className="rounded-lg border border-border p-3 text-muted-foreground">{item.key}</div>
      )}
    </li>
  );
}

export function DatasetDetailView({ id }: { id: string }) {
  const query = useDataset(id);
  const dataset = query.data;
  useBreadcrumbLabel(id, dataset?.name);

  if (query.isError && !dataset) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  return (
    <>
      <PageHeader
        eyebrow="Concevoir · Datasets"
        title={dataset?.name ?? "Dataset"}
        icon={<Database />}
        description={dataset ? dataset.description || DATASET_KIND_META[dataset.kind].description : undefined}
        meta={dataset ? <DatasetKindBadge kind={dataset.kind} /> : null}
      />
      <Card>
        <CardHeader>
          <CardTitle>{dataset?.kind === "gold" ? "Exécutions de référence" : "Documents"}</CardTitle>
          {dataset ? (
            <CardDescription>
              {dataset.items_count} élément{dataset.items_count > 1 ? "s" : ""} · version {dataset.version} · mis à jour{" "}
              <RelativeTime date={dataset.updated_at} />
            </CardDescription>
          ) : null}
        </CardHeader>
        <CardContent>
          {query.isPending ? (
            <TableSkeleton rows={4} className="p-0" />
          ) : !dataset || dataset.items.length === 0 ? (
            <EmptyState icon={<Database />} title="Dataset vide" description="Ajoutez des éléments depuis l'API ou l'import de scénarios." />
          ) : (
            <ul className="grid gap-2">
              {dataset.items.map((item) =>
                dataset.kind === "gold" ? <GoldItem key={item.id} item={item} /> : <ContextItem key={item.id} item={item} />,
              )}
            </ul>
          )}
        </CardContent>
      </Card>
    </>
  );
}
