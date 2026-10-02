"use client";

import * as React from "react";
import { Equal, GitCompareArrows, Hash, Pencil } from "lucide-react";

import { useUrlState } from "@/components/agents/kit/use-url-state";
import { DifficultyBadge } from "@/components/domain/enum-badge";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { RelativeTime } from "@/components/domain/relative-time";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useScenarioVersions, type ScenarioDetail, type ScenarioVersion } from "@/lib/api/scenarios";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { shortHash } from "@/components/agents/labels";
import { ScenarioContent } from "./scenario-content";

const COMPARED_FIELDS: Array<{ key: keyof ScenarioVersion; label: string }> = [
  { key: "difficulty", label: "Difficulté" },
  { key: "description", label: "Description" },
  { key: "input", label: "Entrée" },
  { key: "context", label: "Contexte" },
  { key: "constraints", label: "Contraintes" },
  { key: "expected_output", label: "Résultat attendu" },
  { key: "expected_behavior", label: "Comportement attendu" },
  { key: "criteria", label: "Critères" },
  { key: "rules", label: "Règles" },
  { key: "tool_mocks", label: "Mocks d'outils" },
  { key: "dataset_id", label: "Dataset" },
];

function show(value: unknown): React.ReactNode {
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) {
    return <span className="italic text-subtle-foreground">vide</span>;
  }
  if (typeof value === "string") return <span className="whitespace-pre-wrap break-words">{value}</span>;
  return <pre className="whitespace-pre-wrap break-all font-mono text-[11.5px] leading-relaxed">{JSON.stringify(value, null, 2)}</pre>;
}

/** Versions tab: list, view any version, field-by-field comparison of two versions. */
export function ScenarioVersionsTab({ scenario }: { scenario: ScenarioDetail }) {
  const versions = useScenarioVersions(scenario.id);
  const url = useUrlState();
  const view = url.get("view") === "compare" ? "compare" : "view";
  const list = versions.data ?? [];
  const selectedId = url.get("version") || list[0]?.id || "";
  const selected = list.find((v) => v.id === selectedId) ?? list[0];

  if (versions.isPending) return <Skeleton className="h-96 w-full rounded-xl" />;
  if (versions.isError) return <ErrorState error={versions.error} onRetry={() => void versions.refetch()} />;

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <Card className="self-start">
        <CardHeader>
          <CardTitle>Historique</CardTitle>
          <CardDescription>Versions immuables, la plus récente en premier.</CardDescription>
        </CardHeader>
        <CardContent className="px-2 pb-2">
          <ul className="grid gap-1" role="listbox" aria-label="Versions">
            {list.map((v) => {
              const active = view === "view" && v.id === selected?.id;
              return (
                <li key={v.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={active}
                    onClick={() => url.set({ version: v.id, view: null }, { resetPage: false })}
                    className={cn(
                      "grid w-full gap-1 rounded-md px-3 py-2 text-left transition-colors hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      active && "bg-brand-soft/70 hover:bg-brand-soft",
                    )}
                  >
                    <span className="flex items-center gap-2">
                      <span className="font-mono text-[13px] font-semibold">v{v.version}</span>
                      {v.version === scenario.latest_version ? (
                        <Badge tone="orange" dot>
                          Dernière
                        </Badge>
                      ) : null}
                      <span className="ml-auto text-[11px] text-muted-foreground">
                        <RelativeTime date={v.created_at} />
                      </span>
                    </span>
                    <span className={cn("line-clamp-2 text-xs", v.changelog ? "text-muted-foreground" : "italic text-subtle-foreground")}>
                      {v.changelog || "Sans journal"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </CardContent>
      </Card>

      <div className="grid min-w-0 content-start gap-4">
        <SegmentedControl
          aria-label="Affichage"
          value={view}
          onValueChange={(v) => url.set({ view: v === "compare" ? "compare" : null }, { resetPage: false })}
          options={[
            { value: "view", label: "Consulter" },
            { value: "compare", label: "Comparer deux versions", icon: <GitCompareArrows aria-hidden />, disabled: list.length < 2 },
          ]}
        />
        {view === "compare" && list.length >= 2 ? (
          <CompareVersions versions={list} />
        ) : selected ? (
          <>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span className="font-mono text-sm font-semibold text-foreground">Version {selected.version}</span>
              <DifficultyBadge value={selected.difficulty} withTooltip={false} />
              <span>{formatDateTime(selected.created_at)}</span>
              <span className="flex items-center gap-1 font-mono" title={selected.content_hash}>
                <Hash className="size-3.5" aria-hidden />
                {shortHash(selected.content_hash)}
              </span>
            </div>
            <ScenarioContent version={selected} />
          </>
        ) : null}
      </div>
    </div>
  );
}

function CompareVersions({ versions }: { versions: ScenarioVersion[] }) {
  const url = useUrlState();
  const options = versions.map((v) => ({ value: v.id, label: `v${v.version}`, description: v.changelog.slice(0, 60) || undefined }));
  const b = versions.find((v) => v.id === url.get("b")) ?? versions[0]!;
  const a = versions.find((v) => v.id === url.get("a")) ?? versions.find((v) => v.id !== b.id) ?? versions[1]!;
  const redacted = a.redacted || b.redacted;
  const rows = COMPARED_FIELDS.map((f) => {
    const before = a[f.key];
    const after = b[f.key];
    return { ...f, before, after, same: JSON.stringify(before ?? null) === JSON.stringify(after ?? null) };
  });
  const changed = rows.filter((r) => !r.same);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Comparaison champ par champ</CardTitle>
        <CardDescription>Contenu des deux versions côte à côte ; les champs identiques sont repliés.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field id="cmp-a" label="Version de référence">
            <SimpleSelect id="cmp-a" value={a.id} onValueChange={(v) => url.set({ a: v, b: b.id }, { resetPage: false })} options={options} />
          </Field>
          <Field id="cmp-b" label="Version comparée">
            <SimpleSelect id="cmp-b" value={b.id} onValueChange={(v) => url.set({ b: v, a: a.id }, { resetPage: false })} options={options} />
          </Field>
        </div>
        {redacted ? <RedactedNotice description="Le contenu de ce scénario privé est masqué : seule l'empreinte de contenu peut être comparée." /> : null}
        {a.content_hash === b.content_hash ? (
          <Alert tone="blue" icon={<Equal aria-hidden />} title="Contenu identique">
            Les deux versions ont la même empreinte de contenu.
          </Alert>
        ) : (
          <p className="text-[13px] text-muted-foreground">
            {changed.length} champ{changed.length > 1 ? "s" : ""} modifié{changed.length > 1 ? "s" : ""} entre v{a.version} et v{b.version}.
          </p>
        )}
        {!redacted ? (
          <div className="grid gap-2">
            {rows.map((r) =>
              r.same ? (
                <div key={r.key} className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-[13px] text-muted-foreground">
                  <Equal className="size-3.5" aria-hidden /> {r.label} <span className="text-xs">identique</span>
                </div>
              ) : (
                <div key={r.key} className="grid gap-2 rounded-lg border border-amber-300/70 p-3 dark:border-amber-400/30">
                  <p className="flex items-center gap-1.5 text-[13px] font-medium">
                    <Pencil className="size-3.5 text-amber-600 dark:text-amber-400" aria-hidden /> {r.label}
                  </p>
                  <div className="grid gap-2 md:grid-cols-2">
                    <div className="min-w-0 rounded-md border border-red-200 bg-red-50/60 p-2 text-[12.5px] dark:border-red-400/20 dark:bg-red-400/[0.06]">
                      <span className="mb-1 block text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">v{a.version}</span>
                      <div className="max-h-72 overflow-auto">{show(r.before)}</div>
                    </div>
                    <div className="min-w-0 rounded-md border border-emerald-200 bg-emerald-50/60 p-2 text-[12.5px] dark:border-emerald-400/20 dark:bg-emerald-400/[0.06]">
                      <span className="mb-1 block text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">v{b.version}</span>
                      <div className="max-h-72 overflow-auto">{show(r.after)}</div>
                    </div>
                  </div>
                </div>
              ),
            )}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
