"use client";

import * as React from "react";
import { Braces, Brain, Cpu, KeyRound, Network, Server, Tags, Wallet, Wrench } from "lucide-react";

import { ContextSourceBadge } from "@/components/domain/enum-badge";
import { ProviderKindBadge } from "@/components/domain/enum-badge";
import { CostDisplay, DurationDisplay } from "@/components/domain/metric-display";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeBlock } from "@/components/ui/code-block";
import { JsonViewer } from "@/components/ui/json-viewer";
import type { AgentVersion } from "@/lib/api/agents";
import { formatNumber, formatTokens, plural } from "@/lib/format";

import { DetailList, Empty } from "./kit/detail-list";
import { promptVariables } from "./labels";

function Section({
  icon,
  title,
  description,
  children,
  className,
}: {
  icon: React.ReactNode;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 [&_svg]:size-4 [&_svg]:text-muted-foreground">
          {icon}
          {title}
        </CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function JsonOrEmpty({ data, empty }: { data: Record<string, unknown>; empty: string }) {
  if (!data || Object.keys(data).length === 0) return <p className="text-[13px] text-subtle-foreground">{empty}</p>;
  return <JsonViewer data={data} defaultExpandDepth={2} maxHeightClassName="max-h-80" />;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Full, read-only configuration of an immutable agent version. */
export function VersionConfig({ version }: { version: AgentVersion }) {
  const model = version.model_configuration;
  const vars = promptVariables(version.system_prompt);
  const budget = version.budget;
  const context = version.context_config;
  const contextSource = typeof context.source === "string" ? context.source : "scenario";
  const orbit = context.orbit && typeof context.orbit === "object" ? (context.orbit as Record<string, unknown>) : null;

  return (
    <div className="grid gap-4">
      {version.contamination.length ? (
        <Alert tone="amber" title={`${plural(version.contamination.length, "alerte")} de contamination`}>
          Du contenu de scénarios privés a été détecté dans la configuration de cette version (prompt, outils…). Les
          résultats sur ces scénarios ne mesurent plus la généralisation.
          <JsonViewer data={version.contamination} className="mt-2" maxHeightClassName="max-h-48" />
        </Alert>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        <Section icon={<Server />} title="Adapter & endpoint">
          <DetailList
            items={[
              { label: "Endpoint", value: version.endpoint ? <span className="break-all font-mono text-xs">{version.endpoint}</span> : <Empty /> },
              { label: "Concurrence maximale", value: version.max_concurrency ?? <Empty>Défaut de la plateforme</Empty> },
              {
                label: "Configuration de l'adapter",
                full: true,
                value: <JsonOrEmpty data={version.adapter_config} empty="Aucune configuration spécifique." />,
              },
            ]}
          />
        </Section>

        <Section icon={<Cpu />} title="Modèle" description={model ? `Configuration « ${model.name} »` : undefined}>
          {model ? (
            <DetailList
              items={[
                { label: "Fournisseur", value: model.provider },
                { label: "Modèle", value: <span className="font-mono text-xs">{model.model}</span> },
                { label: "Version du modèle", value: model.model_version ?? <Empty /> },
                { label: "Température", value: model.temperature ?? <Empty /> },
                { label: "Top p", value: model.top_p ?? <Empty /> },
                { label: "Tokens max.", value: model.max_tokens ? formatTokens(model.max_tokens) : <Empty /> },
                { label: "Graine", value: model.seed ?? <Empty /> },
                {
                  label: "Tarif (par million de tokens)",
                  value:
                    model.input_cost_per_mtok !== null && model.input_cost_per_mtok !== undefined ? (
                      <span>
                        Entrée <CostDisplay value={model.input_cost_per_mtok} /> · Sortie <CostDisplay value={model.output_cost_per_mtok} />
                      </span>
                    ) : (
                      <Empty>Tarif connu du modèle ou rapporté par l&apos;agent</Empty>
                    ),
                },
                Object.keys(model.params).length ? { label: "Paramètres", full: true, value: <JsonViewer data={model.params} /> } : null,
              ]}
            />
          ) : (
            <p className="text-[13px] text-subtle-foreground">Pas de configuration de modèle (l&apos;agent gère son propre modèle).</p>
          )}
        </Section>
      </div>

      <Section
        icon={<Brain />}
        title="Prompt système"
        description={version.prompt ? `Prompt versionné « ${version.prompt.name} » v${version.prompt.version}` : "Prompt en ligne"}
      >
        {version.system_prompt ? (
          <div className="grid gap-2">
            <CodeBlock code={version.system_prompt} language="prompt" title="system" wrap maxHeightClassName="max-h-[32rem]" />
            {vars.length ? (
              <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                Variables :
                {vars.map((v) => (
                  <Badge key={v} tone="violet" mono>{`{{${v}}}`}</Badge>
                ))}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-[13px] text-subtle-foreground">Aucun prompt système.</p>
        )}
      </Section>

      <Section
        icon={<Wrench />}
        title="Outils"
        description={
          version.tool_configuration
            ? `Configuration « ${version.tool_configuration.name} » v${version.tool_configuration.version}`
            : undefined
        }
      >
        {version.tools.length ? (
          <ul className="grid gap-3">
            {version.tools.map((tool, i) => (
              <li key={String(tool.name ?? i)} className="grid gap-1.5 rounded-lg border border-border p-3">
                <p className="font-mono text-[13px] font-semibold">{String(tool.name ?? "—")}</p>
                {tool.description ? <p className="text-[13px] text-muted-foreground">{String(tool.description)}</p> : null}
                {tool.parameters ? <JsonViewer data={tool.parameters} maxHeightClassName="max-h-60" /> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-subtle-foreground">Aucun outil déclaré.</p>
        )}
      </Section>

      <div className="grid gap-4 xl:grid-cols-2">
        <Section icon={<Network />} title="Contexte">
          <div className="grid gap-3">
            <div className="flex items-center gap-2 text-[13px]">
              Source : <ContextSourceBadge value={contextSource} />
            </div>
            {orbit ? (
              <DetailList
                items={[
                  { label: "Projet ORBIT", value: String(orbit.project ?? "—") },
                  { label: "Snapshot", value: orbit.snapshot ? String(orbit.snapshot) : <Empty /> },
                  { label: "Version", value: String(orbit.version ?? "latest") },
                  { label: "URL", value: orbit.base_url ? <span className="font-mono text-xs">{String(orbit.base_url)}</span> : <Empty>Défaut</Empty> },
                ]}
              />
            ) : null}
            <JsonOrEmpty data={context} empty="Configuration par défaut (contexte du scénario)." />
          </div>
        </Section>
        <Section icon={<Braces />} title="Mémoire & orchestration">
          <div className="grid gap-3">
            <div className="grid gap-1.5">
              <p className="text-xs font-medium text-muted-foreground">Mémoire</p>
              <JsonOrEmpty data={version.memory_config} empty="Aucune configuration de mémoire." />
            </div>
            <div className="grid gap-1.5">
              <p className="text-xs font-medium text-muted-foreground">Orchestration</p>
              <JsonOrEmpty data={version.orchestration_config} empty="Aucune configuration d'orchestration." />
            </div>
          </div>
        </Section>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Section icon={<Wallet />} title="Budget">
          <DetailList
            items={[
              { label: "Tokens max.", value: num(budget.max_tokens) !== null ? formatTokens(num(budget.max_tokens)) : <Empty>Illimité</Empty> },
              { label: "Coût max.", value: num(budget.max_cost) !== null ? <CostDisplay value={num(budget.max_cost)} /> : <Empty>Illimité</Empty> },
              { label: "Tours max.", value: num(budget.max_steps) !== null ? formatNumber(num(budget.max_steps), 0) : <Empty /> },
              {
                label: "Délai max.",
                value:
                  num(budget.timeout_seconds) !== null ? (
                    <DurationDisplay ms={(num(budget.timeout_seconds) ?? 0) * 1000} />
                  ) : (
                    <Empty>Défaut de la plateforme</Empty>
                  ),
              },
            ]}
          />
        </Section>
        <Section icon={<KeyRound />} title="Identifiant fournisseur">
          {version.credential ? (
            <DetailList
              items={[
                { label: "Nom", value: version.credential.name },
                { label: "Type", value: <ProviderKindBadge value={version.credential.kind} /> },
                { label: "Secret", value: <span className="font-mono text-xs">{version.credential.secret_hint ?? "••••"}</span> },
              ]}
            />
          ) : (
            <p className="text-[13px] text-subtle-foreground">Aucun identifiant : l&apos;agent est appelé sans secret.</p>
          )}
        </Section>
      </div>

      {Object.keys(version.metadata).length ? (
        <Section icon={<Tags />} title="Métadonnées">
          <JsonViewer data={version.metadata} />
        </Section>
      ) : null}
    </div>
  );
}
