"use client";

/** Dashboard API (`GET /dashboard?days=&agent_id=`) — docs/ARCHITECTURE.md §12 (analytics). */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { http } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema } from "./types";

export type Dashboard = ApiSchema<"DashboardOut">;
export type DashboardKpis = ApiSchema<"DashboardKpisOut">;
export type DashboardPreviousKpis = ApiSchema<"PreviousKpisOut">;
export type DashboardTrendPoint = ApiSchema<"TrendPointOut">;
export type DashboardTopError = ApiSchema<"TopErrorOut">;
export type DashboardRecentExperiment = ApiSchema<"RecentExperimentOut">;
export type DashboardAttention = ApiSchema<"DashboardAttentionOut">;
export type WorkerActivity = ApiSchema<"WorkerActivityOut">;

/** Periods offered by the dashboard selector (days). */
export const DASHBOARD_PERIODS = [7, 30, 90] as const;
export type DashboardPeriod = (typeof DASHBOARD_PERIODS)[number];

export const dashboardApi = {
  get: (days: number, agentId: string | undefined, signal?: AbortSignal) =>
    http.get<Dashboard>("/dashboard", { query: { days, agent_id: agentId }, signal }),
};

/** Overview indicators over the last `days` days, optionally for one system (refreshed every minute). */
export function useDashboard(days: number, agentId?: string) {
  return useQuery({
    queryKey: queryKeys.list("dashboard", { days, agent_id: agentId }),
    queryFn: ({ signal }) => dashboardApi.get(days, agentId, signal),
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });
}

/** Jobs queued / running per worker queue (Exécutions page). */
export function useWorkerActivity() {
  return useQuery({
    queryKey: [...queryKeys.resource("runs"), "worker-activity"],
    queryFn: ({ signal }) => http.get<WorkerActivity>("/workers/activity", { signal }),
    refetchInterval: 15_000,
    meta: { toastError: false },
  });
}

/** Query string that opens a list (runs, errors) on the same period and system as the overview. */
export function dashboardScopeQuery(data: Dashboard, extra: Record<string, string>): string {
  const params = new URLSearchParams(extra);
  if (data.agent_id) params.set("agent_id", data.agent_id);
  params.set("from", data.since.slice(0, 10));
  return params.toString();
}
