"use client";

import * as React from "react";
import Link from "next/link";
import { GitBranchPlus, ShieldAlert, SlidersHorizontal } from "lucide-react";

import { RequireRole } from "@/components/auth/require-role";
import { BackLink, DetailSkeleton, HashChip, MetaItem } from "@/components/benchmarks/common";
import { AggregationMethodBadge, GateActionBadge, JudgeProviderBadge } from "@/components/domain/enum-badge";
import { DimensionBadge } from "@/components/domain/dimension-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { useBreadcrumbLabel } from "@/components/layout/shell-context";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeBlock } from "@/components/ui/code-block";
import { ErrorState } from "@/components/ui/error-state";
import { JsonViewer } from "@/components/ui/json-viewer";
import { PageHeader } from "@/components/ui/page-header";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useEvaluationConfig, useForgeMeta, type NormalizationValue } from "@/lib/api/evaluation-configs";
import { AGGREGATION_METHOD_META, criterionDimension, getMeta } from "@/lib/enums";
import { formatDateTime, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AGGREGATION_HELP, asGate, describeGate, NORMALIZATION_FIELDS, WeightsBar } from "./config-helpers";
import { PreviewPanel } from "./preview-panel";

export function ConfigDetailView({ id }: { id: string }) {
  const query = useEvaluationConfig(id);
  const meta = useForgeMeta();
  useBreadcrumbLabel(id, query.data ? `${query.data.name} v${query.data.version}` : null);

  if (query.isPending) return <DetailSkeleton />;
  if (query.isError)
    return (
      <>
        <BackLink href="/evaluation-configs">Configurations</BackLink>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </>
    );
  const c = query.data;
  const versions = [...(c.versions ?? [])].sort((a, b) => b.version - a.version);
  const latest = versions.find((v) => v.is_latest);
  const norm = c.normalization as NormalizationValue;
  const agg = c.aggregation as { method?: string; weights?: Record<string, number>; expression?: string | null };
  const criterionWeights = Object.entries(c.criterion_weights);
  const criteriaName = (key: string) => meta.data?.criteria.find((x) => x.key === key)?.name ?? key;

  return (
    <>
      <BackLink href="/evaluation-configs">Configurations</BackLink>
      <PageHeader
        eyebrow="Configuration d'évaluation"
        title={c.name}
        icon={<SlidersHorizontal />}
        meta={
          <>
            <Badge variant="outline" size="md">
              v{c.version}
            </Badge>
            {c.is_default ? (
              <Badge tone="orange" size="md">
                Par défaut
              </Badge>
            ) : null}
          </>
        }
        description={
          <span className="grid gap-1">
            <span className="font-mono text-xs">{c.key}</span>
            {c.description ? <span>{c.description}</span> : null}
          </span>
        }
        actions={
          <RequireRole min="maintainer">
            <Button asChild size="sm">
              <Link href={`/evaluation-configs/${c.id}/versions/new`}>
                <GitBranchPlus aria-hidden /> Nouvelle version
              </Link>
            </Button>
          </RequireRole>
        }
      />
      {!c.is_latest && latest ? (
        <Alert
          tone="amber"
          className="mb-4"
          action={
            <Button asChild size="xs" variant="secondary">
              <Link href={`/evaluation-configs/${latest.id}`}>Voir la v{latest.version}</Link>
            </Button>
          }
        >
          Vous consultez une ancienne version de cette configuration.
        </Alert>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Pondération des dimensions</CardTitle>
              <CardDescription>
                Composite = 100 × Σ wᵈ·sᵈ / Σ wᵈ sur les dimensions disponibles (renormalisation si une dimension manque).
              </CardDescription>
            </CardHeader>
            <CardContent>
              <WeightsBar weights={c.dimension_weights} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldAlert className="size-4 text-muted-foreground" aria-hidden />
                Garde-fous ({c.gates.length})
              </CardTitle>
              <CardDescription>Évalués après le composite ; un run est réussi s&apos;il n&apos;échoue à aucun garde-fou et atteint le seuil.</CardDescription>
            </CardHeader>
            <CardContent>
              {c.gates.length ? (
                <ul className="grid gap-2">
                  {c.gates.map((g, i) => {
                    const gate = asGate(g);
                    return (
                      <li key={gate.id || i} className="grid gap-1 rounded-lg border border-border p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <GateActionBadge value={gate.action} />
                          <span className="font-mono text-xs text-muted-foreground">{gate.id}</span>
                        </div>
                        <p className="text-[13px] font-medium">{describeGate(gate, meta.data)}</p>
                        {gate.description ? <p className="text-[12.5px] text-muted-foreground">{gate.description}</p> : null}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="text-[13px] text-muted-foreground">Aucun garde-fou.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Pondération des critères</CardTitle>
              <CardDescription>Poids dans la moyenne de leur dimension (défaut : poids du critère).</CardDescription>
            </CardHeader>
            <Table dense>
              <TableHeader>
                <TableRow>
                  <TableHead>Critère</TableHead>
                  <TableHead>Dimension</TableHead>
                  <TableHead className="text-right">Poids</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {criterionWeights.length === 0 ? (
                  <TableEmptyRow colSpan={3}>Poids par défaut des critères.</TableEmptyRow>
                ) : (
                  criterionWeights.map(([k, w]) => (
                    <TableRow key={k}>
                      <TableCell>
                        <span className="grid">
                          <span>{criteriaName(k)}</span>
                          <span className="font-mono text-[11px] text-muted-foreground">{k}</span>
                        </span>
                      </TableCell>
                      <TableCell>{criterionDimension(k) ? <DimensionBadge dimension={criterionDimension(k) as string} /> : "—"}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatNumber(w)}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </Card>

          <PreviewPanel configId={c.id} />
        </div>

        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Réussite et agrégation</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <dl className="grid grid-cols-2 gap-4">
                <MetaItem label="Seuil de réussite">{formatNumber(c.pass_threshold, 1)} / 100</MetaItem>
                <MetaItem label="Scores humains">
                  {c.use_human_scores ? "Remplacent les scores IA" : "Non utilisés dans le composite"}
                </MetaItem>
                <MetaItem label="Agrégation multi-juges" className="col-span-2">
                  <span className="grid gap-1">
                    <AggregationMethodBadge value={agg.method ?? "mean"} />
                    <span className="text-xs text-muted-foreground">{getMeta(AGGREGATION_METHOD_META, agg.method ?? "mean").description}</span>
                  </span>
                </MetaItem>
              </dl>
              {agg.method === "custom" && agg.expression ? (
                <div className="grid gap-1">
                  <CodeBlock code={agg.expression} language="expr" />
                  <p className="text-[11.5px] text-muted-foreground">{AGGREGATION_HELP}</p>
                </div>
              ) : null}
              {agg.method === "weighted" && agg.weights && Object.keys(agg.weights).length ? (
                <ul className="grid gap-1 text-[13px]">
                  {Object.entries(agg.weights).map(([k, w]) => (
                    <li key={k} className="flex justify-between">
                      <span className="font-mono text-xs">{k}</span>
                      <span className="tabular-nums">{formatNumber(w)}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Juges épinglés ({c.judges?.length ?? 0})</CardTitle>
              <CardDescription>Versions exactes figées dans le manifeste de chaque run.</CardDescription>
            </CardHeader>
            <CardContent>
              {c.judges?.length ? (
                <ul className="grid gap-2">
                  {c.judges.map((j) => (
                    <li key={j.id} className={cn("flex flex-wrap items-center gap-2 rounded-md border border-border px-2.5 py-2 text-[13px]", !j.enabled && "opacity-60")}>
                      <Link href={`/judges/${j.id}`} className="font-medium hover:underline">
                        {j.name}
                      </Link>
                      <Badge variant="outline">v{j.version}</Badge>
                      <JudgeProviderBadge value={j.provider} />
                      <span className="text-xs text-muted-foreground">{j.model}</span>
                      <span className="ml-auto text-xs tabular-nums text-muted-foreground">poids {formatNumber(j.weight)}</span>
                      {!j.is_latest ? <Badge tone="amber">Version non à jour</Badge> : null}
                      {!j.enabled ? <Badge tone="neutral">Désactivé</Badge> : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-muted-foreground">Aucun juge : seules les règles et métriques notent les runs.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Normalisation</CardTitle>
              <CardDescription>Cibles linéaires des métriques de coût, latence et robustesse.</CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-3">
                {NORMALIZATION_FIELDS.map((f) => (
                  <MetaItem key={f.key} label={f.label}>
                    <span className="tabular-nums">{formatNumber(norm[f.key])}</span>
                  </MetaItem>
                ))}
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Critères et règles globaux</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3">
              <div className="flex flex-wrap gap-1">
                {c.criteria.length ? (
                  c.criteria.map((k) => (
                    <Badge key={k} mono variant="outline">
                      {k}
                    </Badge>
                  ))
                ) : (
                  <span className="text-[13px] text-muted-foreground">Aucun critère jugé ajouté.</span>
                )}
              </div>
              {c.rules.length ? (
                <JsonViewer data={c.rules} rootLabel="rules" defaultExpandDepth={2} maxHeightClassName="max-h-72" />
              ) : (
                <p className="text-[13px] text-muted-foreground">Aucune règle globale.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Versions</CardTitle>
              <CardDescription className="flex items-center gap-1">
                Empreinte <HashChip hash={c.content_hash} />
              </CardDescription>
            </CardHeader>
            <Table dense>
              <TableBody>
                {versions.map((v) => (
                  <TableRow key={v.id} selected={v.id === c.id}>
                    <TableCell>
                      <Link href={`/evaluation-configs/${v.id}`} className="font-medium hover:underline">
                        v{v.version}
                      </Link>
                      {v.is_latest ? (
                        <Badge tone="orange" className="ml-1.5">
                          Dernière
                        </Badge>
                      ) : null}
                      {v.is_default ? (
                        <Badge tone="blue" className="ml-1.5">
                          Défaut
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground" title={formatDateTime(v.created_at)}>
                      <RelativeTime date={v.created_at} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        </div>
      </div>
    </>
  );
}
