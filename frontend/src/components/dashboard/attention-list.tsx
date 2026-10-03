"use client";

import Link from "next/link";
import {
  ArrowRight,
  CircleCheck,
  ClipboardCheck,
  FlaskConical,
  OctagonAlert,
  ShieldX,
  TriangleAlert,
} from "lucide-react";

import { useNavBadges } from "@/components/layout/use-nav-badges";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentUser } from "@/hooks/use-current-user";
import { dashboardScopeQuery, type Dashboard } from "@/lib/api/dashboard";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

type Level = "critical" | "warning" | "info";

interface AttentionItem {
  key: string;
  level: Level;
  count: number;
  title: string;
  description: string;
  href: string;
  action: string;
  icon: React.ComponentType<{ className?: string }>;
}

const LEVEL_META: Record<Level, { label: string; chip: string; rank: number }> = {
  critical: {
    label: "Critique",
    chip: "bg-red-500/12 text-red-700 dark:text-red-300",
    rank: 0,
  },
  warning: {
    label: "À surveiller",
    chip: "bg-amber-500/15 text-amber-800 dark:text-amber-300",
    rank: 1,
  },
  info: {
    label: "Information",
    chip: "bg-sky-500/12 text-sky-800 dark:text-sky-300",
    rank: 2,
  },
};

const MAX_ITEMS = 5;

/** Builds the list from real figures only: an item exists only when its count is > 0. */
function buildItems(data: Dashboard, reviews: number | undefined): AttentionItem[] {
  const a = data.attention;
  const items: AttentionItem[] = [];
  for (const err of a.critical_errors) {
    items.push({
      key: `error-${err.error_type}`,
      level: "critical",
      count: err.count,
      title: `${formatNumber(err.count, 0)} cas « ${err.label} »`,
      description: `Erreur critique sur ${formatNumber(err.runs_affected, 0)} exécution${err.runs_affected > 1 ? "s" : ""}`,
      href: `/errors?${dashboardScopeQuery(data, { type: err.error_type })}`,
      action: "Analyser",
      icon: OctagonAlert,
    });
  }
  if (a.experiments_with_regression > 0) {
    const one = a.experiments_with_regression === 1 && a.latest_regression;
    items.push({
      key: "regressions",
      level: "critical",
      count: a.experiments_with_regression,
      title: `${a.experiments_with_regression} expérience${a.experiments_with_regression > 1 ? "s présentent" : " présente"} une régression`,
      description: a.latest_regression ? `Dernière : ${a.latest_regression.name}` : "Régressions critiques détectées",
      href:
        one && a.latest_regression
          ? `/experiments/${a.latest_regression.id}`
          : "/experiments?recommendation=do_not_ship",
      action: "Comparer",
      icon: FlaskConical,
    });
  }
  if (reviews && reviews > 0) {
    items.push({
      key: "reviews",
      level: "warning",
      count: reviews,
      title: `${reviews} évaluation${reviews > 1 ? "s attendent" : " attend"} une revue humaine`,
      // The review queue is global: say so when the overview is filtered on one system.
      description: data.agent_id
        ? "File commune à tous les systèmes · désaccord entre juges ou confiance faible"
        : "Désaccord entre juges, confiance faible ou jeu de référence",
      href: "/reviews",
      action: "Revoir",
      icon: ClipboardCheck,
    });
  }
  if (a.gate_failed_runs > 0) {
    items.push({
      key: "gates",
      level: "warning",
      count: a.gate_failed_runs,
      title: `${a.gate_failed_runs} évaluation${a.gate_failed_runs > 1 ? "s bloquées" : " bloquée"} par un garde-fou`,
      description: "Score forcé ou plafonné par une règle de sécurité",
      href: `/runs?${dashboardScopeQuery(data, { gate_failed: "true" })}`,
      action: "Voir",
      icon: ShieldX,
    });
  }
  if (a.interrupted_runs > 0) {
    items.push({
      key: "interrupted",
      level: "warning",
      count: a.interrupted_runs,
      title: `${a.interrupted_runs} exécution${a.interrupted_runs > 1 ? "s interrompues" : " interrompue"}`,
      description: "Erreur technique, délai dépassé ou budget atteint",
      href: `/runs?${dashboardScopeQuery(data, { status: "failed" })}`,
      action: "Voir",
      icon: TriangleAlert,
    });
  }
  return items.sort((x, y) => LEVEL_META[x.level].rank - LEVEL_META[y.level].rank).slice(0, MAX_ITEMS);
}

/** Level 1: what calls for an action, most severe first, each with its next step. */
export function AttentionList({ data, className }: { data: Dashboard | undefined; className?: string }) {
  const { hasRole } = useCurrentUser();
  const badges = useNavBadges();
  const reviews = hasRole("evaluator") ? badges.reviewQueue?.count : undefined;
  const items = data ? buildItems(data, reviews) : [];

  return (
    <Card className={cn("h-full", className)}>
      <CardHeader className="flex-row items-center">
        <CardTitle>À traiter</CardTitle>
        <CardAction>
          <Link
            href="/results"
            className="inline-flex items-center gap-1 rounded text-[13px] font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Voir tout <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        </CardAction>
      </CardHeader>
      <CardContent>
        {!data ? (
          <div className="grid gap-2">
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <p className="flex items-center gap-2 rounded-lg bg-emerald-500/8 px-3 py-3 text-[13px] text-emerald-800 dark:text-emerald-300">
            <CircleCheck className="size-4 shrink-0" aria-hidden />
            Rien à traiter sur la période : aucune erreur critique, régression ou revue en attente.
          </p>
        ) : (
          <ul className="grid gap-1.5">
            {items.map((item) => {
              const meta = LEVEL_META[item.level];
              const Icon = item.icon;
              return (
                <li key={item.key}>
                  <Link
                    href={item.href}
                    className="group flex items-center gap-3 rounded-lg border border-border px-3 py-2.5 transition-colors hover:border-border-strong hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span
                      className={cn("flex size-8 shrink-0 items-center justify-center rounded-md", meta.chip)}
                      aria-hidden
                    >
                      <Icon className="size-4" />
                    </span>
                    <span className="grid min-w-0 flex-1 leading-tight">
                      <span className="line-clamp-2 text-[13.5px] font-medium text-foreground sm:line-clamp-1">
                        {item.title}
                      </span>
                      <span className="line-clamp-2 text-[12px] text-muted-foreground sm:line-clamp-1">
                        <span className="sr-only">{meta.label} — </span>
                        {item.description}
                      </span>
                    </span>
                    <span className="inline-flex shrink-0 items-center gap-1 text-[12.5px] font-medium text-primary group-hover:underline">
                      {item.action}
                      <ArrowRight className="size-3.5" aria-hidden />
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
