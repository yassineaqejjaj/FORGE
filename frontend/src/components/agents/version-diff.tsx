"use client";

import * as React from "react";
import { ArrowRight, Equal, Minus, Pencil, Plus } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CopyButton } from "@/components/ui/code-block";
import type { AgentVersionDiff } from "@/lib/api/agents";
import { plural } from "@/lib/format";
import { cn } from "@/lib/utils";

import { agentFieldLabel } from "./labels";

function render(value: unknown): React.ReactNode {
  if (value === null || value === undefined || value === "") return <span className="italic text-subtle-foreground">vide</span>;
  if (typeof value === "string") return <span className="whitespace-pre-wrap break-words">{value}</span>;
  if (typeof value === "number" || typeof value === "boolean") return <span className="font-mono">{String(value)}</span>;
  return <pre className="whitespace-pre-wrap break-all font-mono text-[11.5px] leading-relaxed">{JSON.stringify(value, null, 2)}</pre>;
}

/** Side-by-side field changes + unified prompt diff + tools diff, as computed by the API. */
export function VersionDiffView({ diff }: { diff: AgentVersionDiff }) {
  const changes = diff.changes.filter((c) => c.field !== "system_prompt");
  const promptChanged = diff.changes.some((c) => c.field === "system_prompt");
  const tools = diff.tools_diff;
  const toolsChanged = tools.added.length + tools.removed.length + tools.changed.length > 0;

  return (
    <div className="grid gap-4">
      {diff.same_content_hash ? (
        <Alert tone="blue" icon={<Equal aria-hidden />} title="Comportement identique">
          Les deux versions ont la même empreinte de contenu : seules des métadonnées non comportementales diffèrent.
        </Alert>
      ) : null}
      {diff.changes.length === 0 ? (
        <Alert tone="neutral" title="Aucune différence">
          v{diff.against_version} et v{diff.version} ont exactement la même configuration.
        </Alert>
      ) : null}

      {changes.length ? (
        <Card>
          <CardHeader>
            <CardTitle>Champs modifiés</CardTitle>
            <CardDescription>{plural(changes.length, "champ modifié", "champs modifiés")}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <div className="hidden grid-cols-[12rem_minmax(0,1fr)_minmax(0,1fr)] gap-3 px-1 text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground lg:grid">
              <span>Champ</span>
              <span>v{diff.against_version} (référence)</span>
              <span>v{diff.version}</span>
            </div>
            {changes.map((c) => (
              <div
                key={c.field}
                className="grid gap-2 rounded-lg border border-border p-3 lg:grid-cols-[12rem_minmax(0,1fr)_minmax(0,1fr)] lg:gap-3"
              >
                <p className="text-[13px] font-medium">
                  {agentFieldLabel(c.field)}
                  <span className="block font-mono text-[11px] font-normal text-subtle-foreground">{c.field}</span>
                </p>
                <div className="min-w-0 rounded-md border border-red-200 bg-red-50/60 p-2 text-[12.5px] text-red-950 dark:border-red-400/20 dark:bg-red-400/[0.06] dark:text-red-100">
                  <span className="mb-1 block text-[10.5px] font-semibold uppercase tracking-wide opacity-70 lg:hidden">
                    v{diff.against_version}
                  </span>
                  {render(c.before)}
                </div>
                <div className="min-w-0 rounded-md border border-emerald-200 bg-emerald-50/60 p-2 text-[12.5px] text-emerald-950 dark:border-emerald-400/20 dark:bg-emerald-400/[0.06] dark:text-emerald-100">
                  <span className="mb-1 block text-[10.5px] font-semibold uppercase tracking-wide opacity-70 lg:hidden">
                    v{diff.version}
                  </span>
                  {render(c.after)}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {toolsChanged ? (
        <Card>
          <CardHeader>
            <CardTitle>Outils</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {tools.added.map((t) => (
              <Badge key={`a-${t}`} tone="green" icon={<Plus aria-hidden />} mono>
                {t}
              </Badge>
            ))}
            {tools.removed.map((t) => (
              <Badge key={`r-${t}`} tone="red" icon={<Minus aria-hidden />} mono>
                {t}
              </Badge>
            ))}
            {tools.changed.map((t) => (
              <Badge key={`c-${t}`} tone="amber" icon={<Pencil aria-hidden />} mono>
                {t}
              </Badge>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {promptChanged || diff.prompt_diff ? (
        <Card>
          <CardHeader className="flex-row items-center">
            <div className="grid gap-1">
              <CardTitle>Prompt système</CardTitle>
              <CardDescription className="flex items-center gap-1.5">
                v{diff.against_version} <ArrowRight className="size-3.5" aria-hidden /> v{diff.version}
              </CardDescription>
            </div>
            {diff.prompt_diff ? <CopyButton value={diff.prompt_diff} label="Copier le diff" className="ml-auto" /> : null}
          </CardHeader>
          <CardContent>
            <UnifiedDiff text={diff.prompt_diff} />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

/** Unified diff with +/- line colouring (signs kept for non-colour readers). */
export function UnifiedDiff({ text }: { text: string }) {
  const lines = text.replace(/\n$/, "").split("\n");
  if (!text.trim()) return <p className="text-[13px] text-subtle-foreground">Prompt inchangé.</p>;
  return (
    <div className="overflow-auto rounded-lg border border-border bg-muted/30 font-mono text-[12px] leading-relaxed" tabIndex={0}>
      <pre className="min-w-max p-0">
        {lines.map((line, i) => {
          const header = line.startsWith("+++") || line.startsWith("---");
          const hunk = line.startsWith("@@");
          const add = !header && line.startsWith("+");
          const del = !header && line.startsWith("-");
          return (
            <div
              key={i}
              className={cn(
                "whitespace-pre-wrap px-3",
                header && "bg-muted font-semibold text-muted-foreground",
                hunk && "bg-blue-50 text-blue-800 dark:bg-blue-400/10 dark:text-blue-200",
                add && "bg-emerald-50 text-emerald-900 dark:bg-emerald-400/10 dark:text-emerald-100",
                del && "bg-red-50 text-red-900 dark:bg-red-400/10 dark:text-red-100",
              )}
            >
              {line || " "}
            </div>
          );
        })}
      </pre>
    </div>
  );
}
