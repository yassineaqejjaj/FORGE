"use client";

import { useQuery } from "@tanstack/react-query";

import { http, type ApiError } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema } from "./types";

export type Arena = ApiSchema<"EfficiencyOut">;
export type ArenaCategory = ApiSchema<"EfficiencyCategoryOut">;
export type ArenaModel = ApiSchema<"ModelStatsOut">;

export const ARENA_PERIODS = [7, 30, 90] as const;

/** « Analyser › Arène des modèles » : per kind of work, which model succeeds how often and at what cost. */
export function useArena(params: { days: number; agent_id?: string }) {
  return useQuery<Arena, ApiError>({
    queryKey: queryKeys.list("arena", params),
    queryFn: ({ signal }) => http.get<Arena>("/analytics/efficiency", { query: params, signal }),
    staleTime: 30_000,
  });
}
