"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http, type ApiError } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema } from "./types";

export type RedTeamReport = ApiSchema<"RedTeamReportOut">;
export type RedTeamFamily = ApiSchema<"RedTeamFamilyOut">;
export type RedTeamAttack = ApiSchema<"RedTeamAttackOut">;
export type RedTeamLaunch = ApiSchema<"RedTeamLaunchOut">;

export const REDTEAM_PERIODS = [7, 30, 90] as const;

/** Red team: the attack catalogue, a launch against an agent version, and how the agent held up. */
export function useRedTeamCatalog() {
  return useQuery<RedTeamAttack[], ApiError>({
    queryKey: queryKeys.list("redteam", { part: "catalog" }),
    queryFn: ({ signal }) => http.get<RedTeamAttack[]>("/redteam/catalog", { signal }),
    staleTime: 60_000,
  });
}

export function useRedTeamReport(params: { agent_version_id?: string; days: number }) {
  return useQuery<RedTeamReport, ApiError>({
    queryKey: queryKeys.list("redteam", { part: "report", ...params }),
    queryFn: ({ signal }) => http.get<RedTeamReport>("/redteam/report", { query: params, signal }),
    enabled: Boolean(params.agent_version_id),
    // Runs are evaluated by workers in the background: follow them while the report is still filling in.
    refetchInterval: (query) => (query.state.data?.status === "not_run" ? 5_000 : false),
  });
}

export function useLaunchRedTeam() {
  const client = useQueryClient();
  return useMutation<RedTeamLaunch, ApiError, { agent_version_id: string; repetitions?: number }>({
    mutationFn: (body) => http.post<RedTeamLaunch>("/redteam/runs", body),
    meta: { silentError: true },
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.resource("redteam") }),
  });
}
