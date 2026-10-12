"use client";

import * as React from "react";
import Link from "next/link";
import { ShieldAlert, ShieldCheck, Swords } from "lucide-react";

import { useUrlState } from "@/components/benchmarks/use-url-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Progress } from "@/components/ui/progress";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { useHasRole } from "@/hooks/use-current-user";
import { useAgentVersionOptions } from "@/lib/api/benchmarks";
import { REDTEAM_PERIODS, useLaunchRedTeam, useRedTeamCatalog, useRedTeamReport, type RedTeamFamily } from "@/lib/api/redteam";
import { useAgentOptions } from "@/lib/api/runs";
import { formatPercent } from "@/lib/format";

const STATUS: Record<string, { label: string; tone: "green" | "amber" | "red" | "neutral" }> = {
  solid: { label: "Solide", tone: "green" },
  fragile: { label: "Fragile", tone: "amber" },
  weak: { label: "Faible", tone: "red" },
  not_run: { label: "Pas encore évaluée", tone: "neutral" },
};

const VERDICT: Record<string, { label: string; hint: string }> = {
  solid: { label: "Résistance solide", hint: "Toutes les familles d’attaques évaluées sont bien tenues." },
  fragile: { label: "Résistance fragile", hint: "Certaines familles passent de justesse : à renforcer avant un usage sensible." },
  vulnerable: { label: "Vulnérable", hint: "Au moins une famille d’attaques réussit régulièrement : à corriger avant de déployer." },
  not_run: { label: "Aucune attaque évaluée", hint: "Lancez le catalogue sur cette version pour mesurer sa résistance." },
};

function FamilyCard({ family }: { family: RedTeamFamily }) {
  const meta = STATUS[family.status] ?? STATUS.not_run;
  const value = family.resistance === null ? null : Math.round(family.resistance * 100);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          {family.label}
          <Badge tone={meta?.tone ?? "neutral"}>{meta?.label}</Badge>
        </CardTitle>
        <CardDescription>{family.summary}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2">
        <div className="flex items-baseline justify-between text-sm">
          <span className="text-muted-foreground">
            {family.runs ? `${family.resisted} résistée${family.resisted > 1 ? "s" : ""} sur ${family.runs}` : "—"}
          </span>
          <span className="font-semibold tabular-nums">{family.resistance === null ? "—" : formatPercent(family.resistance)}</span>
        </div>
        <Progress value={value} tone={family.status === "solid" ? "green" : family.status === "weak" ? "red" : "amber"} aria-label={`Résistance : ${family.label}`} />
        {Object.keys(family.error_types).length ? (
          <p className="text-xs text-muted-foreground">
            Détecté : {Object.entries(family.error_types).map(([type, n]) => `${type} ×${n}`).join(", ")}
          </p>
        ) : null}
        {family.failed_run_ids.length ? (
          <p className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Exécutions en cause :</span>
            {family.failed_run_ids.map((id) => (
              <Link key={id} href={`/runs/${id}`} className="text-brand hover:underline">
                {id.slice(0, 8)}
              </Link>
            ))}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

/**
 * « Tester › Red team » : the same attacks every time (prompt injection, leaks, tool abuse…) against one agent
 * version, and how it held up. The detectors are deterministic rules — no model grades another model here.
 */
export function RedTeamView() {
  const { get, set } = useUrlState();
  const canLaunch = useHasRole("editor");
  const agentId = get("agent_id") ?? undefined;
  const versionId = get("agent_version_id") ?? undefined;
  const daysParam = Number(get("days"));
  const days = (REDTEAM_PERIODS as readonly number[]).includes(daysParam) ? daysParam : 30;
  const agents = useAgentOptions();
  const versions = useAgentVersionOptions(agentId);
  const report = useRedTeamReport({ agent_version_id: versionId, days });
  const catalog = useRedTeamCatalog();
  const launch = useLaunchRedTeam();
  const verdict = VERDICT[report.data?.status ?? "not_run"] ?? VERDICT.not_run;
  const launchError = launch.error?.message;
  return (
    <div className="grid gap-6">
      <PageHeader
        icon={<ShieldAlert />}
        title="Red team"
        description="Les mêmes attaques à chaque fois — injection de prompt, fuite de données confidentielles, détournement d’outil — contre une version d’agent, et la mesure de sa résistance. Les détecteurs sont des règles déterministes : aucun modèle ne juge un autre modèle."
      />
      <div className="flex flex-wrap items-center gap-3">
        <SimpleSelect
          aria-label="Agent"
          value={agentId ?? ""}
          placeholder="Choisir un agent"
          onValueChange={(v) => set({ agent_id: v, agent_version_id: null })}
          options={(agents.data?.items ?? []).map((a) => ({ value: a.id, label: a.name }))}
        />
        <SimpleSelect
          aria-label="Version d'agent"
          value={versionId ?? ""}
          placeholder={agentId ? "Choisir une version" : "Choisir d’abord un agent"}
          disabled={!agentId}
          onValueChange={(v) => set({ agent_version_id: v })}
          options={[...(versions.data ?? [])]
            .sort((a, b) => b.version_number - a.version_number)
            .map((v) => ({ value: v.id, label: `v${v.version}${v.model ? ` · ${v.model}` : ""}` }))}
        />
        <SegmentedControl
          aria-label="Période"
          value={String(days)}
          onValueChange={(v) => set({ days: v })}
          options={REDTEAM_PERIODS.map((d) => ({ value: String(d), label: `${d} jours` }))}
        />
        {canLaunch ? (
          <Button
            variant="primary"
            disabled={!versionId || launch.isPending}
            onClick={() => versionId && launch.mutate({ agent_version_id: versionId })}
          >
            <Swords aria-hidden /> Lancer les attaques
          </Button>
        ) : null}
      </div>
      {launch.isSuccess ? (
        <p role="status" className="text-sm text-muted-foreground">
          {launch.data.attacks} attaques lancées. Le rapport se complète à mesure que les exécutions sont évaluées.
        </p>
      ) : null}
      {launchError ? <p role="alert" className="text-sm text-danger">{launchError}</p> : null}
      {!versionId ? (
        <EmptyState
          icon={<ShieldCheck />}
          title="Choisissez une version d’agent"
          description={`Le catalogue compte ${catalog.data?.length ?? "plusieurs"} familles d’attaques. Sélectionnez une version pour voir sa résistance, ou la lancer.`}
        />
      ) : null}
      {report.isError ? <ErrorState error={report.error} onRetry={() => report.refetch()} /> : null}
      {report.data ? (
        <>
          <Card>
            <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6">
              <div>
                <p className="text-lg font-semibold">{verdict?.label}</p>
                <p className="text-sm text-muted-foreground">{verdict?.hint}</p>
              </div>
              <p className="text-3xl font-semibold tabular-nums">{report.data.resistance === null ? "—" : formatPercent(report.data.resistance)}</p>
            </CardContent>
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            {report.data.families.map((f) => (
              <FamilyCard key={f.key} family={f} />
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
