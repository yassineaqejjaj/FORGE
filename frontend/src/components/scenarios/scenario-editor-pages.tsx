"use client";

import * as React from "react";
import Link from "next/link";
import { FilePlus2, ScrollText } from "lucide-react";

import { roleRequirement } from "@/components/agents/kit/role-button";
import { useUrlState } from "@/components/agents/kit/use-url-state";
import { RedactedNotice } from "@/components/domain/redacted-notice";
import { useBreadcrumbLabel } from "@/components/layout/shell-context";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { PageHeader } from "@/components/ui/page-header";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useScenario, useScenarioVersions } from "@/lib/api/scenarios";
import { formatDate } from "@/lib/format";

import { contentFromVersion } from "./editor-model";
import { ScenarioEditor } from "./scenario-editor";

function Restricted({ message }: { message: string }) {
  return <EmptyState size="lg" icon={<ScrollText />} title="Accès réservé" description={message} />;
}

/** `/scenarios/new`. */
export function NewScenarioView() {
  const { hasRole, isLoading } = useCurrentUser();
  useBreadcrumbLabel("new", "Nouveau scénario");
  return (
    <>
      <PageHeader
        eyebrow="Scénarios"
        title="Nouveau scénario"
        icon={<FilePlus2 />}
        description="Entrée, contexte, contraintes, résultat attendu, critères, règles et mocks d'outils. Les scénarios privés sont réservés aux mainteneurs."
      />
      {isLoading ? <Skeleton className="h-96 w-full rounded-xl" /> : hasRole("editor") ? <ScenarioEditor mode="create" /> : <Restricted message={roleRequirement("editor")} />}
    </>
  );
}

/** `/scenarios/{id}/versions/new?from=<versionId>` (defaults to the latest version). */
export function NewScenarioVersionView({ scenarioId }: { scenarioId: string }) {
  const scenario = useScenario(scenarioId);
  const versions = useScenarioVersions(scenarioId);
  const url = useUrlState();
  const { hasRole, isLoading } = useCurrentUser();
  useBreadcrumbLabel(scenarioId, scenario.data?.name);
  useBreadcrumbLabel("versions", "Versions");
  useBreadcrumbLabel("new", "Nouvelle version");

  const list = versions.data ?? [];
  const from = list.find((v) => v.id === url.get("from")) ?? list[0];
  const initial = React.useMemo(() => (from && !from.redacted ? contentFromVersion(from) : undefined), [from]);

  if (scenario.isError) return <ErrorState error={scenario.error} onRetry={() => void scenario.refetch()} />;
  const s = scenario.data;

  return (
    <>
      <PageHeader
        eyebrow={
          s ? (
            <Link href={`/scenarios/${s.id}`} className="hover:underline">
              {s.name}
            </Link>
          ) : (
            "Scénario"
          )
        }
        title="Nouvelle version"
        icon={<FilePlus2 />}
        description="Le contenu d'une version est immuable : la nouvelle version reçoit sa propre empreinte et un nouveau canari."
        actions={
          list.length > 1 ? (
            <Field id="from-version" label="Partir de">
              <SimpleSelect
                id="from-version"
                size="sm"
                value={from?.id}
                onValueChange={(v) => url.set({ from: v })}
                options={list.map((v) => ({ value: v.id, label: `v${v.version}`, description: formatDate(v.created_at) }))}
                className="w-40"
              />
            </Field>
          ) : null
        }
      />
      {scenario.isPending || versions.isPending || isLoading ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : versions.isError ? (
        <ErrorState error={versions.error} onRetry={() => void versions.refetch()} />
      ) : !hasRole("editor") ? (
        <Restricted message={roleRequirement("editor")} />
      ) : from?.redacted || (s?.visibility === "private" && !hasRole("maintainer")) ? (
        <div className="grid gap-4">
          <RedactedNotice description="Le contenu de ce scénario privé est réservé aux mainteneurs : vous ne pouvez pas en créer de nouvelle version." />
          <Button asChild variant="secondary" className="w-fit">
            <Link href={`/scenarios/${scenarioId}`}>Retour au scénario</Link>
          </Button>
        </div>
      ) : s ? (
        <ScenarioEditor key={from?.id ?? "empty"} mode="version" scenario={s} initialContent={initial} basedOn={from ? `v${from.version}` : undefined} />
      ) : null}
    </>
  );
}
