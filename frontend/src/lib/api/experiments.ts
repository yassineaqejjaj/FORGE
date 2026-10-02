"use client";

/**
 * Experiments API (docs/ARCHITECTURE.md §9.3, docs/CI.md): baseline vs candidate, paired comparison,
 * CI gate, feedback reports. Every statistic (deltas, CI, p-values, verdicts, regressions,
 * recommendation) is computed by the API — the UI only renders it.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { isActiveExecution, LIVE_POLL_MS } from "./benchmarks";
import { http } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema, Page } from "./types";

export type Experiment = ApiSchema<"ExperimentOut">;
export type ExperimentDetail = ApiSchema<"ExperimentDetailOut">;
export type ExperimentCreateInput = ApiSchema<"ExperimentCreateIn">;
export type Comparison = ApiSchema<"ComparisonOut">;
export type MetricComparison = ApiSchema<"MetricComparisonOut">;
export type ResourceComparison = ApiSchema<"ResourceComparisonOut">;
export type ScenarioChange = ApiSchema<"ScenarioChangeOut">;
export type ErrorChange = ApiSchema<"ErrorChangeOut">;
export type ArmSummary = ApiSchema<"ArmSummaryOut">;
export type Gate = ApiSchema<"GateOut">;
export type FeedbackReport = ApiSchema<"FeedbackReportOut">;

export interface ExperimentListParams {
  page?: number;
  page_size?: number;
  status?: string;
  recommendation?: string;
  agent_id?: string;
  benchmark_id?: string;
  search?: string;
}

export const experimentsApi = {
  list: (params: ExperimentListParams = {}) => http.get<Page<Experiment>>("/experiments", { query: { ...params } }),
  get: (id: string) => http.get<ExperimentDetail>(`/experiments/${id}`),
  create: (body: ExperimentCreateInput) => http.post<ExperimentDetail>("/experiments", body),
  comparison: (id: string) => http.get<Comparison>(`/experiments/${id}/comparison`),
  gate: (id: string, strict: boolean) => http.get<Gate>(`/experiments/${id}/gate`, { query: { strict } }),
  cancel: (id: string) => http.post<ExperimentDetail>(`/experiments/${id}/cancel`),
  feedbackReport: (id: string) => http.get<FeedbackReport>(`/feedback-reports/${id}`),
};

export function useExperiments(params: ExperimentListParams) {
  return useQuery({
    queryKey: queryKeys.list("experiments", { ...params }),
    queryFn: () => experimentsApi.list(params),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((e) => isActiveExecution(e.status)) ? LIVE_POLL_MS * 2 : false,
  });
}

export function useExperiment(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.detail("experiments", id ?? ""),
    queryFn: () => experimentsApi.get(id as string),
    enabled: Boolean(id),
    refetchInterval: (query) => (isActiveExecution(query.state.data?.status) ? LIVE_POLL_MS : false),
  });
}

export function useComparison(id: string | undefined, options: { enabled?: boolean; live?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.sub("experiments", id ?? "", "comparison"),
    queryFn: () => experimentsApi.comparison(id as string),
    enabled: Boolean(id) && (options.enabled ?? true),
    refetchInterval: options.live ? LIVE_POLL_MS * 3 : false,
  });
}

export function useGate(id: string | undefined, strict: boolean, enabled = true) {
  return useQuery({
    queryKey: queryKeys.sub("experiments", id ?? "", "gate", { strict }),
    queryFn: () => experimentsApi.gate(id as string, strict),
    enabled: Boolean(id) && enabled,
  });
}

export function useFeedbackReport(id: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.detail("feedback-reports", id ?? ""),
    queryFn: () => experimentsApi.feedbackReport(id as string),
    enabled: Boolean(id),
    staleTime: 5 * 60_000,
  });
}

export function useCreateExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: experimentsApi.create,
    meta: { silentError: true, successMessage: "Expérience créée et lancée" },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("experiments") }),
  });
}

export function useCancelExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => experimentsApi.cancel(id),
    meta: { successMessage: "Expérience annulée" },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("experiments") }),
  });
}

/** CLI command reproducing the CI gate decision (docs/CI.md §2). */
export function gateCliCommand(experimentId: string, strict: boolean): string {
  return `forge experiment gate ${experimentId}${strict ? " --strict" : ""}`;
}
