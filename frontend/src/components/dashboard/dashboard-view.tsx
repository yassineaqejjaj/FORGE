"use client";

import { FlaskConical, Layers, LayoutDashboard, Play } from "lucide-react";

import { RoleButton } from "@/components/agents/kit/role-button";
import { useUrlState } from "@/components/agents/kit/use-url-state";
import { useEnvironment } from "@/components/layout/context-switcher";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { DASHBOARD_PERIODS, useDashboard, type DashboardPeriod } from "@/lib/api/dashboard";
import { useAgentOptions } from "@/lib/api/runs";
import { cn } from "@/lib/utils";

import { AttentionList } from "./attention-list";
import { OverviewContext } from "./overview-context";
import { OverviewKpis } from "./overview-kpis";
import { PerformanceChart } from "./performance-chart";
import { RecentExperiments } from "./recent-experiments";
import { TopErrors } from "./top-errors";

const ALL_SYSTEMS = "__all__";
const UUID = /^[0-9a-f-]{36}$/i;

function parsePeriod(raw: string): DashboardPeriod {
  const n = Number(raw);
  return (DASHBOARD_PERIODS as readonly number[]).includes(n) ? (n as DashboardPeriod) : 30;
}

/**
 * Vue d'ensemble : `GET /dashboard?days=&agent_id=` (all figures are computed by the API).
 *
 * Three reading levels: (1) quality and what needs attention, (2) performance over time, error
 * causes and experiments, (3) the inventory line. Mobile order: quality, « À traiter », the other
 * KPIs, then the rest (CSS `order`, the DOM keeps the desktop reading order of the KPI row).
 */
export function DashboardView() {
  const url = useUrlState();
  const days = parsePeriod(url.get("days"));
  const rawAgent = url.get("agent_id");
  const agentId = UUID.test(rawAgent) ? rawAgent : undefined;
  const query = useDashboard(days, agentId);
  const data = query.data;

  return (
    <>
      <PageHeader
        title="Vue d'ensemble"
        icon={<LayoutDashboard />}
        description="Vue d'ensemble des évaluations : scores, coûts, latences, erreurs et activité récente."
        meta={query.isFetching && !query.isPending ? <Spinner label="Actualisation…" /> : null}
      >
        {/* Filters and actions share one toolbar under the title: the description keeps its width. */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <HeaderFilters days={days} agentId={agentId} onChange={(updates) => url.set(updates)} />
          <QuickActions />
        </div>
      </PageHeader>

      {query.isError && !data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div className={cn("grid gap-4 transition-opacity", query.isPlaceholderData && "opacity-70")}>
          <OverviewContext data={data} />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <OverviewKpis data={data} days={days} />
            <AttentionList data={data} className="order-2 sm:col-span-2" />
            <PerformanceChart data={data} className="order-4 sm:col-span-2" />
            <TopErrors data={data} days={days} className="order-5 sm:col-span-2" />
            <RecentExperiments data={data} className="order-6 sm:col-span-2" />
          </div>
        </div>
      )}
    </>
  );
}

function HeaderFilters({
  days,
  agentId,
  onChange,
}: {
  days: DashboardPeriod;
  agentId: string | undefined;
  onChange: (updates: Record<string, string | null>) => void;
}) {
  const agents = useAgentOptions();
  const environment = useEnvironment();
  const options = [
    { value: ALL_SYSTEMS, label: "Tous les systèmes" },
    ...(agents.data?.items ?? [])
      .filter((a) => !a.archived || a.id === agentId)
      .map((a) => ({ value: a.id, label: a.name })),
  ];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SimpleSelect
        aria-label="Système évalué"
        size="sm"
        className="w-[200px] max-w-full"
        value={agentId ?? ALL_SYSTEMS}
        onValueChange={(v) => onChange({ agent_id: v === ALL_SYSTEMS ? null : v })}
        options={options}
      />
      {environment ? (
        <span
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-card px-2.5 text-[12.5px] text-muted-foreground"
          title="Environnement de déploiement de FORGE"
        >
          <span className={cn("size-1.5 rounded-full", environment.tone)} aria-hidden />
          <span className="sr-only">Environnement : </span>
          {environment.label}
        </span>
      ) : null}
      <SegmentedControl
        aria-label="Période"
        value={String(days)}
        onValueChange={(v) => onChange({ days: v === "30" ? null : v })}
        options={DASHBOARD_PERIODS.map((d) => ({
          value: String(d),
          label: `${d} j`,
        }))}
      />
    </div>
  );
}

/** Secondary actions get a shorter label on phones so the three buttons fit on one or two lines. */
function QuickActions() {
  return (
    <section aria-label="Actions rapides" className="flex flex-wrap gap-2">
      <RoleButton minRole="editor" href="/runs?new=1" leftIcon={<Play aria-hidden />} size="sm">
        Nouvelle exécution
      </RoleButton>
      <RoleButton
        minRole="editor"
        href="/benchmarks?new=1"
        aria-label="Nouvelle comparaison"
        variant="secondary"
        leftIcon={<Layers aria-hidden />}
        size="sm"
      >
        <span className="sm:hidden">Comparaison</span>
        <span className="hidden sm:inline">Nouvelle comparaison</span>
      </RoleButton>
      <RoleButton
        minRole="editor"
        href="/experiments?new=1"
        aria-label="Nouvelle expérience"
        variant="secondary"
        leftIcon={<FlaskConical aria-hidden />}
        size="sm"
      >
        <span className="sm:hidden">Expérience</span>
        <span className="hidden sm:inline">Nouvelle expérience</span>
      </RoleButton>
    </section>
  );
}
