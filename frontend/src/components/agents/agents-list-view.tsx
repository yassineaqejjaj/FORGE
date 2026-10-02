"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Bot, FilterX, Plus, TriangleAlert } from "lucide-react";

import { AdapterKindBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { RunStatusBadge } from "@/components/domain/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useAgents, useRunsList, type Agent } from "@/lib/api/agents";
import { DEFAULT_PAGE_SIZE } from "@/lib/api/types";
import { plural } from "@/lib/format";

import { AgentFormDialog } from "./agent-form-dialog";
import { FilterBar, FilterSelect, SearchInput } from "./kit/filters";
import { RoleButton } from "./kit/role-button";
import { useUrlState } from "./kit/use-url-state";

const COLUMNS = 7;

/** Agents list: `GET /agents` with URL-synced search, filters and pagination. */
export function AgentsListView() {
  const url = useUrlState();
  const router = useRouter();
  const [createOpen, setCreateOpen] = React.useState(false);
  const q = url.get("q");
  const provider = url.get("provider");
  const tag = url.get("tag");
  const archived = url.get("archived") === "true";
  const params = { q, provider, tag, archived, page: url.page, page_size: DEFAULT_PAGE_SIZE };
  const query = useAgents(params);
  const hasFilters = Boolean(q || provider || tag || archived);
  const setUrl = url.set;
  const onSearch = React.useCallback((v: string) => setUrl({ q: v }), [setUrl]);

  return (
    <>
      <PageHeader
        eyebrow="Concevoir"
        title="Agents"
        icon={<Bot />}
        description="Agents évalués et leurs versions immuables : prompt, modèle, outils, contexte et budget. Chaque modification de comportement crée une nouvelle version."
        actions={
          <RoleButton minRole="editor" leftIcon={<Plus aria-hidden />} onClick={() => setCreateOpen(true)}>
            Nouvel agent
          </RoleButton>
        }
      />

      <Card>
        <div className="border-b border-border p-3">
          <FilterBar>
            <SearchInput
              value={q}
              onCommit={onSearch}
              placeholder="Rechercher un agent…"
            />
            <ProviderInput value={provider} onCommit={(v) => url.set({ provider: v })} />
            <ProviderInput value={tag} onCommit={(v) => url.set({ tag: v })} placeholder="Étiquette" label="Filtrer par étiquette" />
            <FilterSelect
              aria-label="État"
              value={archived ? "true" : "false"}
              noAll
              allLabel=""
              onValueChange={(v) => url.set({ archived: v === "true" ? "true" : null })}
              options={[
                { value: "false", label: "Agents actifs" },
                { value: "true", label: "Agents archivés" },
              ]}
            />
            {hasFilters ? (
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<FilterX aria-hidden />}
                onClick={() => url.set({ q: null, provider: null, tag: null, archived: null })}
              >
                Réinitialiser
              </Button>
            ) : null}
          </FilterBar>
        </div>

        {query.isError && !query.data ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} variant="plain" />
        ) : (
          <>
            <Table aria-busy={query.isFetching || undefined}>
              <TableHeader>
                <TableRow>
                  <TableHead>Agent</TableHead>
                  <TableHead>Fournisseur</TableHead>
                  <TableHead className="text-right">Versions</TableHead>
                  <TableHead>Dernière version</TableHead>
                  <TableHead>Modèle</TableHead>
                  <TableHead>Dernier run</TableHead>
                  <TableHead>Étiquettes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.isPending ? (
                  Array.from({ length: 6 }, (_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: COLUMNS }, (__, j) => (
                        <TableCell key={j}>
                          <Skeleton className="h-4 w-full max-w-32" />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : query.data && query.data.items.length > 0 ? (
                  query.data.items.map((agent) => (
                    <AgentRow key={agent.id} agent={agent} onOpen={() => router.push(`/agents/${agent.id}`)} />
                  ))
                ) : (
                  <tr>
                    <td colSpan={COLUMNS} className="p-4">
                      <EmptyState
                        variant="plain"
                        icon={<Bot />}
                        title={hasFilters ? "Aucun agent ne correspond aux filtres" : archived ? "Aucun agent archivé" : "Aucun agent enregistré"}
                        description={
                          hasFilters
                            ? "Modifiez la recherche ou réinitialisez les filtres."
                            : "Enregistrez un agent puis sa première version pour commencer à l'évaluer."
                        }
                        action={
                          !hasFilters ? (
                            <RoleButton minRole="editor" size="sm" leftIcon={<Plus aria-hidden />} onClick={() => setCreateOpen(true)}>
                              Nouvel agent
                            </RoleButton>
                          ) : undefined
                        }
                      />
                    </td>
                  </tr>
                )}
              </TableBody>
            </Table>
            {query.data && query.data.total > 0 ? (
              <div className="border-t border-border px-4 py-3">
                <Pagination
                  page={url.page}
                  pageSize={query.data.page_size}
                  total={query.data.total}
                  onPageChange={(p) => url.set({ page: p > 1 ? p : null })}
                  disabled={query.isFetching}
                />
              </div>
            ) : null}
          </>
        )}
      </Card>

      <AgentFormDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  );
}

function ProviderInput({
  value,
  onCommit,
  placeholder = "Fournisseur",
  label = "Filtrer par fournisseur",
}: {
  value: string;
  onCommit: (v: string) => void;
  placeholder?: string;
  label?: string;
}) {
  const [draft, setDraft] = React.useState(value);
  React.useEffect(() => setDraft(value), [value]);
  return (
    <Input
      size="sm"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => draft.trim() !== value && onCommit(draft.trim())}
      onKeyDown={(e) => {
        if (e.key === "Enter") onCommit(draft.trim());
      }}
      placeholder={placeholder}
      aria-label={label}
      className="w-full sm:w-40"
    />
  );
}

function AgentRow({ agent, onOpen }: { agent: Agent; onOpen: () => void }) {
  const latest = agent.latest_version;
  return (
    <TableRow
      interactive
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter") onOpen();
      }}
    >
      <TableCell className="max-w-72">
        <div className="grid min-w-0 gap-0.5">
          <Link
            href={`/agents/${agent.id}`}
            onClick={(e) => e.stopPropagation()}
            className="truncate font-medium text-foreground hover:underline focus-visible:outline-none"
          >
            {agent.name}
          </Link>
          <span className="truncate font-mono text-[11.5px] text-muted-foreground">{agent.slug}</span>
        </div>
      </TableCell>
      <TableCell className="text-muted-foreground">{agent.provider || "—"}</TableCell>
      <TableCell className="text-right tabular-nums">{agent.versions_count}</TableCell>
      <TableCell>
        {latest ? (
          <div className="flex items-center gap-1.5">
            <Badge tone="orange" variant="outline" mono>
              v{latest.version}
            </Badge>
            <AdapterKindBadge value={latest.adapter_kind} withTooltip={false} />
            {latest.contamination_warnings > 0 ? (
              <SimpleTooltip content={`${plural(latest.contamination_warnings, "avertissement")} de contamination`}>
                <span className="inline-flex text-amber-600 dark:text-amber-400">
                  <TriangleAlert className="size-3.5" aria-label="Avertissement de contamination" />
                </span>
              </SimpleTooltip>
            ) : null}
          </div>
        ) : (
          <span className="text-xs text-subtle-foreground">Aucune version</span>
        )}
      </TableCell>
      <TableCell className="font-mono text-xs text-muted-foreground">{latest?.model ?? "—"}</TableCell>
      <TableCell>
        <LastRunCell agentId={agent.id} />
      </TableCell>
      <TableCell>
        <div className="flex max-w-56 flex-wrap gap-1">
          {agent.tags.length ? (
            agent.tags.slice(0, 4).map((t) => (
              <Badge key={t} tone="neutral">
                {t}
              </Badge>
            ))
          ) : (
            <span className="text-subtle-foreground">—</span>
          )}
          {agent.tags.length > 4 ? <Badge tone="neutral">+{agent.tags.length - 4}</Badge> : null}
        </div>
      </TableCell>
    </TableRow>
  );
}

/** Most recent run of the agent (`GET /runs?agent_id=&page_size=1`). */
function LastRunCell({ agentId }: { agentId: string }) {
  const runs = useRunsList({ agent_id: agentId, page_size: 1 });
  if (runs.isPending) return <Skeleton className="h-4 w-24" />;
  const run = runs.data?.items[0];
  if (!run) return <span className="text-xs text-subtle-foreground">Jamais exécuté</span>;
  return (
    <Link
      href={`/runs/${run.id}`}
      onClick={(e) => e.stopPropagation()}
      className="flex items-center gap-1.5 rounded text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <RunStatusBadge status={run.status} />
      <RelativeTime date={run.created_at} />
    </Link>
  );
}
