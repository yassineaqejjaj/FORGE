import type { Metadata } from "next";
import { Bug, Coins, Gauge, LayoutDashboard, Play, Timer } from "lucide-react";

import { KpiCard } from "@/components/domain/kpi-card";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Tableau de bord" };

const KPIS = [
  { label: "Score composite moyen", icon: Gauge },
  { label: "Runs (30 j)", icon: Play },
  { label: "Coût total", icon: Coins },
  { label: "Latence p95", icon: Timer },
  { label: "Erreurs critiques", icon: Bug },
] as const;

/** Dashboard placeholder: layout of the future `GET /dashboard?days=30` view with skeletons. */
export default function DashboardPage() {
  return (
    <>
      <PageHeader
        eyebrow="Pilotage"
        title="Tableau de bord"
        icon={<LayoutDashboard />}
        description="Vue d'ensemble des évaluations : scores, tendances, régressions, coûts et erreurs sur les 30 derniers jours."
        meta={
          <Badge tone="orange" dot>
            En cours d&apos;intégration
          </Badge>
        }
      />
      <section aria-label="Indicateurs clés" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {KPIS.map(({ label, icon: Icon }) => (
          <KpiCard key={label} label={label} icon={<Icon />} value={null} hint="—" loading />
        ))}
      </section>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Évolution du score composite</CardTitle>
            <CardDescription>Par version d&apos;agent, moyenne quotidienne</CardDescription>
          </CardHeader>
          <CardContent>
            <Skeleton className="h-64 w-full" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Dimensions</CardTitle>
            <CardDescription>Moyenne des 8 dimensions d&apos;évaluation</CardDescription>
          </CardHeader>
          <CardContent>
            <Skeleton className="mx-auto aspect-square w-full max-w-64 rounded-full" />
          </CardContent>
        </Card>
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Dernières expériences</CardTitle>
            <CardDescription>Verdicts, régressions et recommandations</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
