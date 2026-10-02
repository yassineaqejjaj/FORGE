"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Download, FilterX, GitFork, Plus, ScrollText, Sparkles, Upload } from "lucide-react";

import { FilterBar, FilterSelect, SearchInput } from "@/components/agents/kit/filters";
import { RoleButton } from "@/components/agents/kit/role-button";
import { useUrlState } from "@/components/agents/kit/use-url-state";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { ClassificationBanner, maxClassification } from "@/components/domain/classification-banner";
import { DifficultyBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
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
import { useScenarios, useMeta, type Scenario } from "@/lib/api/scenarios";
import { DEFAULT_PAGE_SIZE } from "@/lib/api/types";
import { DIFFICULTIES, DIFFICULTY_META, SCENARIO_VISIBILITIES, SCENARIO_VISIBILITY_META } from "@/lib/enums";
import { formatDate, plural } from "@/lib/format";

import { ExportScenariosDialog, ImportScenariosDialog } from "./import-export-dialogs";

const COLUMNS = 8;

/** Scenario library: `GET /scenarios` with URL-synced filters, import / export. */
export function ScenariosListView() {
  const url = useUrlState();
  const router = useRouter();
  const meta = useMeta();
  const [importOpen, setImportOpen] = React.useState(false);
  const [exportOpen, setExportOpen] = React.useState(false);
  const filters = {
    q: url.get("q"),
    category: url.get("category"),
    visibility: url.get("visibility"),
    difficulty: url.get("difficulty"),
    tag: url.get("tag"),
    family: url.get("family"),
    archived: url.get("archived") === "true",
  };
  const query = useScenarios({ ...filters, page: url.page, page_size: DEFAULT_PAGE_SIZE });
  const hasFilters = Object.values(filters).some(Boolean);
  const setUrl = url.set;
  const onSearch = React.useCallback((v: string) => setUrl({ q: v }), [setUrl]);
  const items = query.data?.items ?? [];
  const level = maxClassification(items.map((s) => s.classification));

  return (
    <>
      <PageHeader
        eyebrow="Concevoir"
        title="Scénarios"
        icon={<ScrollText />}
        description="Bibliothèque de scénarios versionnés : publics, privés (contenu caché, test de généralisation) et fresh, avec familles de variantes."
        actions={
          <>
            <RoleButton minRole="editor" variant="secondary" leftIcon={<Upload aria-hidden />} onClick={() => setImportOpen(true)}>
              Importer
            </RoleButton>
            <Button variant="secondary" leftIcon={<Download aria-hidden />} onClick={() => setExportOpen(true)}>
              Exporter
            </Button>
            <RoleButton minRole="editor" href="/scenarios/new" leftIcon={<Plus aria-hidden />}>
              Nouveau scénario
            </RoleButton>
          </>
        }
      />

      <ClassificationBanner level={level} context="display" className="mb-4" compact />

      <Card>
        <div className="border-b border-border p-3">
          <FilterBar>
            <SearchInput value={filters.q} onCommit={onSearch} placeholder="Rechercher (nom, identifiant)…" />
            <FilterSelect
              aria-label="Catégorie"
              allLabel="Toutes les catégories"
              value={filters.category}
              onValueChange={(v) => url.set({ category: v })}
              options={(meta.data?.categories ?? []).map((c) => ({ value: c.value, label: c.label }))}
            />
            <FilterSelect
              aria-label="Visibilité"
              allLabel="Toutes les visibilités"
              value={filters.visibility}
              onValueChange={(v) => url.set({ visibility: v })}
              options={SCENARIO_VISIBILITIES.map((v) => ({ value: v, label: SCENARIO_VISIBILITY_META[v].label }))}
              className="sm:w-40"
            />
            <FilterSelect
              aria-label="Difficulté"
              allLabel="Toutes difficultés"
              value={filters.difficulty}
              onValueChange={(v) => url.set({ difficulty: v })}
              options={DIFFICULTIES.map((d) => ({ value: d, label: DIFFICULTY_META[d].label }))}
              className="sm:w-40"
            />
            <TagFilter value={filters.tag} onCommit={(v) => url.set({ tag: v })} />
            <FilterSelect
              aria-label="État"
              noAll
              allLabel=""
              value={filters.archived ? "true" : "false"}
              onValueChange={(v) => url.set({ archived: v === "true" ? "true" : null })}
              options={[
                { value: "false", label: "Actifs" },
                { value: "true", label: "Archivés" },
              ]}
              className="sm:w-32"
            />
            {filters.family ? (
              <Badge tone="violet" icon={<GitFork aria-hidden />} size="md">
                Famille filtrée
              </Badge>
            ) : null}
            {hasFilters ? (
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<FilterX aria-hidden />}
                onClick={() => url.set({ q: null, category: null, visibility: null, difficulty: null, tag: null, family: null, archived: null })}
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
                  <TableHead>Scénario</TableHead>
                  <TableHead>Catégorie</TableHead>
                  <TableHead>Difficulté</TableHead>
                  <TableHead>Visibilité</TableHead>
                  <TableHead>Classification</TableHead>
                  <TableHead>Famille</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Étiquettes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.isPending ? (
                  Array.from({ length: 6 }, (_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: COLUMNS }, (__, j) => (
                        <TableCell key={j}>
                          <Skeleton className="h-4 w-full max-w-28" />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : items.length ? (
                  items.map((s) => <ScenarioRow key={s.id} scenario={s} onOpen={() => router.push(`/scenarios/${s.id}`)} onFamily={(f) => url.set({ family: f })} />)
                ) : (
                  <tr>
                    <td colSpan={COLUMNS} className="p-4">
                      <EmptyState
                        variant="plain"
                        icon={<ScrollText />}
                        title={hasFilters ? "Aucun scénario ne correspond aux filtres" : "Bibliothèque vide"}
                        description={
                          hasFilters
                            ? "Modifiez la recherche ou réinitialisez les filtres."
                            : "Créez un scénario ou importez un bundle forge.scenarios/v1."
                        }
                        action={
                          !hasFilters ? (
                            <>
                              <RoleButton minRole="editor" size="sm" href="/scenarios/new" leftIcon={<Plus aria-hidden />}>
                                Nouveau scénario
                              </RoleButton>
                              <RoleButton minRole="editor" size="sm" variant="secondary" onClick={() => setImportOpen(true)} leftIcon={<Upload aria-hidden />}>
                                Importer
                              </RoleButton>
                            </>
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

      <ImportScenariosDialog open={importOpen} onOpenChange={setImportOpen} />
      <ExportScenariosDialog
        open={exportOpen}
        onOpenChange={setExportOpen}
        params={{
          q: filters.q || undefined,
          category: filters.category || undefined,
          visibility: filters.visibility || undefined,
          tag: filters.tag || undefined,
          archived: filters.archived,
        }}
        scopeLabel={
          query.data
            ? `${plural(query.data.total, "scénario")} ${hasFilters ? "correspondant aux filtres actuels" : "de la bibliothèque"}`
            : "Scénarios de la bibliothèque"
        }
        maxClassification={level}
      />
    </>
  );
}

function TagFilter({ value, onCommit }: { value: string; onCommit: (v: string) => void }) {
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
      placeholder="Étiquette"
      aria-label="Filtrer par étiquette"
      className="w-full sm:w-36"
    />
  );
}

function ScenarioRow({ scenario: s, onOpen, onFamily }: { scenario: Scenario; onOpen: () => void; onFamily: (familyId: string) => void }) {
  const isVariant = Boolean(s.parent_scenario_id);
  return (
    <TableRow
      interactive
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter") onOpen();
      }}
    >
      <TableCell className="max-w-80">
        <div className="grid min-w-0 gap-0.5">
          <Link href={`/scenarios/${s.id}`} onClick={(e) => e.stopPropagation()} className="truncate font-medium text-foreground hover:underline">
            {s.name}
          </Link>
          <span className="truncate font-mono text-[11.5px] text-muted-foreground">{s.slug}</span>
        </div>
      </TableCell>
      <TableCell className="text-muted-foreground">{s.category_label}</TableCell>
      <TableCell>{s.difficulty ? <DifficultyBadge value={s.difficulty} withTooltip={false} /> : "—"}</TableCell>
      <TableCell>
        <span className="flex items-center gap-1.5">
          <VisibilityBadge visibility={s.visibility} />
          {s.visibility === "fresh" && s.fresh_until ? (
            <SimpleTooltip content={s.is_fresh ? `Fresh jusqu'au ${formatDate(s.fresh_until)}` : `Fraîcheur expirée le ${formatDate(s.fresh_until)}`}>
              <span className={s.is_fresh ? "text-teal-600 dark:text-teal-400" : "text-subtle-foreground"}>
                <Sparkles className="size-3.5" aria-label={s.is_fresh ? "Fresh" : "Fraîcheur expirée"} />
              </span>
            </SimpleTooltip>
          ) : null}
        </span>
      </TableCell>
      <TableCell>
        <ClassificationBadge level={s.classification} showLabel={false} />
      </TableCell>
      <TableCell>
        {isVariant || s.variant_label ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onFamily(s.family_id);
            }}
            className="rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            title="Afficher la famille"
          >
            <Badge tone="violet" icon={<GitFork aria-hidden />}>
              {s.variant_label ?? "Variante"}
            </Badge>
          </button>
        ) : (
          <span className="text-xs text-subtle-foreground">Original</span>
        )}
      </TableCell>
      <TableCell>
        <span className="flex items-center gap-2 whitespace-nowrap">
          <Badge tone="neutral" variant="outline" mono>
            v{s.latest_version}
          </Badge>
          <RelativeTime date={s.updated_at} className="text-xs text-muted-foreground" />
        </span>
      </TableCell>
      <TableCell>
        <div className="flex max-w-48 flex-wrap gap-1">
          {s.tags.length ? s.tags.slice(0, 3).map((t) => <Badge key={t}>{t}</Badge>) : <span className="text-subtle-foreground">—</span>}
          {s.tags.length > 3 ? <Badge>+{s.tags.length - 3}</Badge> : null}
          {s.archived ? <Badge tone="neutral">Archivé</Badge> : null}
        </div>
      </TableCell>
    </TableRow>
  );
}
