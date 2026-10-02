"use client";

import { useQuery } from "@tanstack/react-query";

import { http, type ApiError } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema } from "./types";

export type ResultsOverview = ApiSchema<"ResultsOverviewOut">;
export type ResultsAgentRow = ApiSchema<"ResultsAgentRowOut">;

export const RESULTS_PERIODS = [7, 30, 90] as const;

/** « Analyser › Résultats » : evaluated runs of the window aggregated per agent version. */
export function useResultsOverview(params: { days: number; agent_id?: string }) {
  return useQuery<ResultsOverview, ApiError>({
    queryKey: queryKeys.list("results", params),
    queryFn: ({ signal }) => http.get<ResultsOverview>("/results/overview", { query: params, signal }),
    staleTime: 30_000,
  });
}
