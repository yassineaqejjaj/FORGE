"use client";

import * as React from "react";
import { ShieldCheck, ShieldX } from "lucide-react";

import { RecommendationBadge } from "@/components/domain/verdict-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeBlock } from "@/components/ui/code-block";
import { ErrorState } from "@/components/ui/error-state";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { gateCliCommand, useGate } from "@/lib/api/experiments";
import { formatSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

/** CI gate decision (`GET /experiments/{id}/gate`) + copyable CLI command. */
export function GateCard({ experimentId, enabled = true }: { experimentId: string; enabled?: boolean }) {
  const [strict, setStrict] = React.useState(false);
  const gate = useGate(experimentId, strict, enabled);
  const cli = `${gateCliCommand(experimentId, strict)}\n# code de sortie : 0 = garde-fou franchi · 1 = en échec · 2 = erreur`;

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <CardTitle>Garde-fou CI</CardTitle>
          <CardDescription>
            Échec si « Ne pas déployer » (composite moins bon, régression critique ou sécurité dégradée). En mode strict,
            seule « Déployer » passe.
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <Switch id="gate-strict" checked={strict} onCheckedChange={setStrict} />
          <Label htmlFor="gate-strict">Mode strict</Label>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4">
        {gate.isPending ? (
          <Skeleton className="h-20" />
        ) : gate.isError ? (
          <ErrorState error={gate.error} onRetry={() => void gate.refetch()} size="sm" />
        ) : (
          <div
            className={cn(
              "flex flex-wrap items-start gap-4 rounded-lg border p-4",
              gate.data.passed
                ? "border-emerald-300 bg-emerald-50 dark:border-emerald-400/30 dark:bg-emerald-400/10"
                : "border-red-300 bg-red-50 dark:border-red-400/30 dark:bg-red-400/10",
            )}
            role="status"
          >
            {gate.data.passed ? (
              <ShieldCheck className="size-8 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
            ) : (
              <ShieldX className="size-8 shrink-0 text-red-600 dark:text-red-400" aria-hidden />
            )}
            <div className="grid min-w-0 flex-1 gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-base font-semibold">{gate.data.passed ? "Garde-fou franchi" : "Garde-fou en échec"}</span>
                {gate.data.recommendation ? <RecommendationBadge recommendation={gate.data.recommendation} size="sm" /> : null}
                {gate.data.strict ? <Badge tone="violet">Strict</Badge> : null}
                <Badge variant="outline">Δ composite {formatSigned(gate.data.composite_delta, { unit: "pts" })}</Badge>
                <Badge variant="outline" tone={gate.data.regressions ? "red" : "neutral"}>
                  {gate.data.regressions} régression(s)
                </Badge>
              </div>
              <ul className="grid gap-0.5 text-[13px] text-foreground/90">
                {gate.data.reasons.map((r) => (
                  <li key={r}>• {r}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
        <CodeBlock code={cli} language="bash" title="Relire la décision en CI" />
      </CardContent>
    </Card>
  );
}
