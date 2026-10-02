"use client";

import * as React from "react";
import Link from "next/link";
import { CopyPlus, Eye, FileText, GitCompareArrows, Hash, TriangleAlert } from "lucide-react";

import { AdapterKindBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useAgentVersion, type AgentVersionSummary } from "@/lib/api/agents";
import { formatDateTime, plural } from "@/lib/format";
import { cn } from "@/lib/utils";

import { RoleButton } from "./kit/role-button";
import { shortHash } from "./labels";

export interface VersionsTimelineProps {
  agentId: string;
  /** Newest first (as returned by the API). */
  versions: ReadonlyArray<AgentVersionSummary>;
}

/** Vertical timeline of immutable agent versions (newest first). */
export function VersionsTimeline({ agentId, versions }: VersionsTimelineProps) {
  return (
    <ol className="relative grid gap-0" aria-label="Versions de l'agent">
      {versions.map((v, i) => {
        const previous = versions[i + 1];
        return (
          <li key={v.id} className="relative grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3 pb-5 last:pb-0">
            <div className="relative flex justify-center" aria-hidden>
              {i < versions.length - 1 ? <span className="absolute top-5 bottom-[-1.25rem] w-px bg-border" /> : null}
              <span
                className={cn(
                  "relative mt-1.5 size-3 rounded-full ring-4 ring-card",
                  i === 0 ? "bg-brand" : "bg-border-strong",
                )}
              />
            </div>
            <VersionItem agentId={agentId} version={v} previous={previous} latest={i === 0} />
          </li>
        );
      })}
    </ol>
  );
}

function VersionItem({
  agentId,
  version,
  previous,
  latest,
}: {
  agentId: string;
  version: AgentVersionSummary;
  previous?: AgentVersionSummary;
  latest: boolean;
}) {
  // Prompt reference is only in the full version payload.
  const detail = useAgentVersion(version.id);
  const prompt = detail.data?.prompt;
  return (
    <div className="grid min-w-0 gap-2 rounded-lg border border-border bg-card p-3.5 shadow-xs">
      <div className="flex flex-wrap items-center gap-2">
        <Link
          href={`/agents/${agentId}/versions/${version.id}`}
          className="font-mono text-sm font-semibold text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          v{version.version}
        </Link>
        {latest ? (
          <Badge tone="orange" dot>
            Dernière
          </Badge>
        ) : null}
        <AdapterKindBadge value={version.adapter_kind} withTooltip={false} />
        {version.contamination_warnings > 0 ? (
          <SimpleTooltip content="Des contenus de scénarios privés (canaris, résultats attendus) ont été détectés dans la configuration de cette version.">
            <span className="inline-flex">
              <Badge tone="amber" icon={<TriangleAlert aria-hidden />}>
                {plural(version.contamination_warnings, "alerte")} de contamination
              </Badge>
            </span>
          </SimpleTooltip>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground" title={formatDateTime(version.created_at)}>
          <RelativeTime date={version.created_at} />
        </span>
      </div>

      <p className={cn("text-[13px] leading-relaxed", version.changelog ? "text-foreground" : "italic text-subtle-foreground")}>
        {version.changelog || "Aucun journal des modifications"}
      </p>

      <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <div className="flex items-center gap-1">
          <dt className="sr-only">Modèle</dt>
          <dd className="font-mono">{version.model ?? "Sans modèle"}</dd>
        </div>
        <div className="flex items-center gap-1">
          <dt className="flex items-center">
            <FileText className="size-3.5" aria-hidden />
            <span className="sr-only">Prompt</span>
          </dt>
          <dd>
            {detail.isPending ? (
              <Skeleton className="h-3 w-20" />
            ) : prompt ? (
              <span className="font-mono">
                {prompt.name} v{prompt.version}
              </span>
            ) : (
              "Prompt en ligne"
            )}
          </dd>
        </div>
        <div className="flex items-center gap-1">
          <dt className="flex items-center">
            <Hash className="size-3.5" aria-hidden />
            <span className="sr-only">Empreinte</span>
          </dt>
          <dd className="font-mono" title={version.content_hash}>
            {shortHash(version.content_hash)}
          </dd>
        </div>
      </dl>

      <div className="flex flex-wrap gap-1.5 pt-0.5">
        <Button asChild variant="secondary" size="xs">
          <Link href={`/agents/${agentId}/versions/${version.id}`}>
            <Eye aria-hidden /> Détail
          </Link>
        </Button>
        {previous ? (
          <Button asChild variant="ghost" size="xs">
            <Link href={`/agents/${agentId}/compare?from=${previous.id}&to=${version.id}`}>
              <GitCompareArrows aria-hidden /> Comparer à v{previous.version}
            </Link>
          </Button>
        ) : null}
        <RoleButton
          minRole="editor"
          variant="ghost"
          size="xs"
          href={`/agents/${agentId}/versions/new?base=${version.id}`}
          leftIcon={<CopyPlus aria-hidden />}
        >
          Nouvelle version basée sur celle-ci
        </RoleButton>
      </div>
    </div>
  );
}
