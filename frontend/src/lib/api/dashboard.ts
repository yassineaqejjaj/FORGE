"use client";

/** Dashboard API (`GET /dashboard?days=`) — docs/ARCHITECTURE.md §12 (analytics). */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { http } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema } from "./types";

export type Dashboard = ApiSchema<"DashboardOut">;
export type DashboardTrendPoint = ApiSchema<"TrendPointOut">;
export type DashboardTopError = ApiSchema<"TopErrorOut">;
export type DashboardRecentExperiment = ApiSchema<"RecentExperimentOut">;
export type DashboardRecentExecution = ApiSchema<"RecentExecutionOut">;

/** Periods offered by the dashboard selector (days). */
export const DASHBOARD_PERIODS = [7, 30, 90] as const;
export type DashboardPeriod = (typeof DASHBOARD_PERIODS)[number];

export const dashboardApi = {
  get: (days: number, signal?: AbortSignal) => http.get<Dashboard>("/dashboard", { query: { days }, signal }),
};

/** Dashboard indicators over the last `days` days (refreshed every minute). */
export function useDashboard(days: number) {
  return useQuery({
    queryKey: queryKeys.list("dashboard", { days }),
    queryFn: ({ signal }) => dashboardApi.get(days, signal),
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });
}
