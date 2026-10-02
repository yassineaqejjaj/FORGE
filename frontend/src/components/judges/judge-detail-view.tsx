"use client";

import * as React from "react";
import Link from "next/link";
import { GitBranchPlus, Gavel } from "lucide-react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { BackLink, DetailSkeleton, HashChip, MetaItem } from "@/components/benchmarks/common";
import { CalibrationStatusBadge, JudgeProviderBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { useBreadcrumbLabel } from "@/components/layout/shell-context";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeBlock } from "@/components/ui/code-block";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useHasRole } from "@/hooks/use-current-user";
import { errorMessage } from "@/lib/api/client";
import { useJudge, useJudgesCalibration, useUpdateJudge, type JudgeDetail } from "@/lib/api/judges";
import { formatDateTime, formatNumber, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import { JudgeTestPanel } from "./judge-test-panel";

function CalibrationCard({ judge }: { judge: JudgeDetail }) {
  const cal = useJudgesCalibration({ judge_id: judge.id });
  const overall = cal.data?.overall;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Calibration humaine</CardTitle>
        <CardDescription>Accord entre ce juge et les évaluations humaines (kappa pondéré, accord à ±0,2).</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {cal.isError ? (
          <p className="text-[13px] text-muted-foreground">Calibration indisponible.</p>
        ) : !overall ? (
          <p className="text-[13px] text-muted-foreground">Chargement…</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <CalibrationStatusBadge value={overall.status} size="md" />
              <span className="text-xs text-muted-foreground">{overall.n} paire(s) IA / humain</span>
            </div>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <MetaItem label="Kappa">{formatNumber(overall.kappa)}</MetaItem>
              <MetaItem label="Accord">{formatPercent(overall.agreement_rate)}</MetaItem>
              <MetaItem label="Écart abs. moyen">{formatNumber(overall.mean_abs_error)}</MetaItem>
              <MetaItem label="Spearman">{formatNumber(overall.spearman)}</MetaItem>
            </dl>
            <Link href={`/calibration?judge_id=${judge.id}`} className="text-[13px] text-primary hover:underline">
              Ouvrir la calibration détaillée
            </Link>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function JudgeDetailView({ id }: { id: string }) {
  const query = useJudge(id);
  const update = useUpdateJudge();
  const canEdit = useHasRole("maintainer");
  useBreadcrumbLabel(id, query.data ? `${query.data.name} v${query.data.version}` : null);

  if (query.isPending) return <DetailSkeleton />;
  if (query.isError)
    return (
      <>
        <BackLink href="/judges">Juges</BackLink>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </>
    );
  const j = query.data;
  const latest = (j.versions ?? []).find((v) => v.is_latest);
  const versions = [...(j.versions ?? [])].sort((a, b) => b.version - a.version);

  return (
    <>
      <BackLink href="/judges">Juges</BackLink>
      <PageHeader
        eyebrow="Juge"
        title={j.name}
        icon={<Gavel />}
        meta={
          <>
            <Badge variant="outline" size="md">
              v{j.version}
            </Badge>
            <JudgeProviderBadge value={j.provider} size="md" />
            {j.enabled ? <Badge tone="green" dot size="md">Activé</Badge> : <Badge tone="neutral" dot size="md">Désactivé</Badge>}
          </>
        }
        description={
          <span className="grid gap-1">
            <span className="font-mono text-xs">{j.key}</span>
            {j.description ? <span>{j.description}</span> : null}
          </span>
        }
        actions={
          <RequireRole min="maintainer">
            <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
              <Switch
                checked={j.enabled}
                disabled={update.isPending || !canEdit}
                onCheckedChange={(enabled) =>
                  update.mutate(
                    { id: j.id, body: { enabled } },
                    {
                      onSuccess: () => toast.success(enabled ? "Juge activé" : "Juge désactivé"),
                      onError: (e) => toast.error(errorMessage(e)),
                    },
                  )
                }
              />
              {j.enabled ? "Activé" : "Désactivé"}
            </label>
            <Button asChild size="sm">
              <Link href={`/judges/${j.id}/versions/new`}>
                <GitBranchPlus aria-hidden /> Nouvelle version
              </Link>
            </Button>
          </RequireRole>
        }
      />
      {!j.is_latest && latest ? (
        <Alert tone="amber" className="mb-4" action={<Button asChild size="xs" variant="secondary"><Link href={`/judges/${latest.id}`}>Voir la v{latest.version}</Link></Button>}>
          Vous consultez une ancienne version de ce juge.
        </Alert>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Configuration</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <MetaItem label="Modèle">
                  {j.model}
                  {j.model_version ? <span className="text-muted-foreground"> ({j.model_version})</span> : null}
                </MetaItem>
                <MetaItem label="Température">{formatNumber(j.temperature)}</MetaItem>
                <MetaItem label="Tokens max.">{formatNumber(j.max_tokens, 0)}</MetaItem>
                <MetaItem label="Poids">{formatNumber(j.weight)}</MetaItem>
                <MetaItem label="URL de base" className="col-span-2">
                  <span className="break-all font-mono text-xs">{j.base_url ?? "Défaut du fournisseur"}</span>
                </MetaItem>
                <MetaItem label="Identifiant fournisseur">
                  {j.credential_id ? (
                    <RequireRole min="admin" fallback={<span className="font-mono text-xs">{j.credential_id.slice(0, 8)}…</span>}>
                      <Link href="/settings/credentials" className="font-mono text-xs text-primary hover:underline">
                        {j.credential_id.slice(0, 8)}…
                      </Link>
                    </RequireRole>
                  ) : (
                    "Environnement"
                  )}
                </MetaItem>
                <MetaItem label="Empreinte">
                  <HashChip hash={j.content_hash} />
                </MetaItem>
              </dl>
              <div className="grid gap-1.5">
                <p className="text-[11.5px] font-medium uppercase tracking-wide text-subtle-foreground">Critères jugés</p>
                {j.criteria.length ? (
                  <div className="flex flex-wrap gap-1">
                    {j.criteria.map((c) => (
                      <Badge key={c} mono variant="outline">
                        {c}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <p className="text-[13px] text-muted-foreground">Tous les critères jugés du scénario et de la configuration.</p>
                )}
              </div>
            </CardContent>
          </Card>
          <CodeBlock title="Prompt système" code={j.system_prompt || "(vide)"} wrap maxHeightClassName="max-h-80" />
          <CodeBlock title="Grille d'évaluation" code={j.rubric_template || "(grille par défaut)"} wrap maxHeightClassName="max-h-[28rem]" />
          <RequireRole
            min="maintainer"
            fallback={<Alert tone="neutral">Le test d&apos;un juge sur un run est réservé aux mainteneurs.</Alert>}
          >
            <JudgeTestPanel judge={j} />
          </RequireRole>
        </div>
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Historique des versions</CardTitle>
              <CardDescription>Versions immuables de la clé {j.key}.</CardDescription>
            </CardHeader>
            <Table dense>
              <TableHeader>
                <TableRow>
                  <TableHead>Version</TableHead>
                  <TableHead>Modèle</TableHead>
                  <TableHead>Créée</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {versions.map((v) => (
                  <TableRow key={v.id} selected={v.id === j.id}>
                    <TableCell>
                      <Link href={`/judges/${v.id}`} className={cn("font-medium hover:underline", v.id === j.id && "text-primary")}>
                        v{v.version}
                      </Link>
                      {v.is_latest ? (
                        <Badge tone="orange" className="ml-1.5">
                          Dernière
                        </Badge>
                      ) : null}
                      {!v.enabled ? (
                        <Badge tone="neutral" className="ml-1.5">
                          Désactivée
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-xs">{v.model}</TableCell>
                    <TableCell className="text-xs text-muted-foreground" title={formatDateTime(v.created_at)}>
                      <RelativeTime date={v.created_at} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
          <CalibrationCard judge={j} />
        </div>
      </div>
    </>
  );
}
