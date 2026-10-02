"use client";

/**
 * Benchmarks API (docs/ARCHITECTURE.md §9.1, §12): definitions, launches (executions) and aggregated
 * results. Also hosts the read-only pickers used by the benchmark / experiment forms (agents,
 * agent versions, scenarios, scenario versions, runs) — thin wrappers over the platform endpoints.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ACTIVE_EXECUTION_STATUSES, type ExecutionStatus } from "@/lib/enums";
import { http } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema, Page } from "./types";

export type Benchmark = ApiSchema<"BenchmarkOut">;
export type BenchmarkDetail = ApiSchema<"BenchmarkDetailOut">;
export type BenchmarkScenario = ApiSchema<"BenchmarkScenarioOut">;
export type AgentVersionRef = ApiSchema<"AgentVersionRefOut">;
export type BenchmarkCreateInput = ApiSchema<"BenchmarkCreateIn">;
export type BenchmarkUpdateInput = ApiSchema<"BenchmarkUpdateIn">;
export type Execution = ApiSchema<"ExecutionOut">;
export type ExecutionDetail = ApiSchema<"ExecutionDetailOut">;
export type BenchmarkSummary = ApiSchema<"BenchmarkSummaryOut">;
export type AgentAggregate = ApiSchema<"AgentAggregateOut">;
export type RankingEntry = ApiSchema<"RankingEntryOut">;
export type MatrixData = ApiSchema<"MatrixOut">;
export type MatrixCell = ApiSchema<"MatrixCellOut">;
export type GroupRow = ApiSchema<"GroupRowOut">;
export type ErrorTypeRow = ApiSchema<"ErrorTypeRowOut">;
export type BenchmarkResults = ApiSchema<"ResultsOut">;
export type GroupBy = BenchmarkResults["group_by"];
export type CancelResult = ApiSchema<"CancelOut">;

export type AgentListItem = ApiSchema<"AgentOut">;
export type AgentVersionSummary = ApiSchema<"AgentVersionSummary">;
export type ScenarioListItem = ApiSchema<"ScenarioOut">;
export type ScenarioVersion = ApiSchema<"ScenarioVersionOut">;
export type RunListItem = ApiSchema<"RunOut">;
export type AgentVersionDetail = ApiSchema<"AgentVersionOut">;

/** Group-by options of `GET /benchmarks/{id}/results`, in display order (French labels). */
export const GROUP_BY_OPTIONS: ReadonlyArray<{ value: GroupBy; label: string }> = [
  { value: "version", label: "Version d'agent" },
  { value: "agent", label: "Agent" },
  { value: "model", label: "Modèle" },
  { value: "scenario", label: "Scénario" },
  { value: "category", label: "Catégorie" },
  { value: "difficulty", label: "Difficulté" },
  { value: "visibility", label: "Visibilité" },
  { value: "family", label: "Famille de variantes" },
  { value: "error_type", label: "Type d'erreur" },
  { value: "date", label: "Date" },
];

export function isActiveExecution(status: string | null | undefined): boolean {
  return Boolean(status) && ACTIVE_EXECUTION_STATUSES.has(status as ExecutionStatus);
}

/** Live polling interval while an execution / experiment is running. */
export const LIVE_POLL_MS = 3000;

export interface BenchmarkListParams {
  page?: number;
  page_size?: number;
  search?: string;
  archived?: boolean;
  tag?: string;
}

export interface ResultsParams {
  execution_id?: string;
  group_by?: GroupBy;
  visibility?: string;
  category?: string;
}

export const benchmarksApi = {
  list: (params: BenchmarkListParams = {}) =>
    http.get<Page<Benchmark>>("/benchmarks", { query: { ...params } }),
  get: (ref: string) => http.get<BenchmarkDetail>(`/benchmarks/${encodeURIComponent(ref)}`),
  create: (body: BenchmarkCreateInput) => http.post<BenchmarkDetail>("/benchmarks", body),
  update: (ref: string, body: BenchmarkUpdateInput) =>
    http.patch<BenchmarkDetail>(`/benchmarks/${encodeURIComponent(ref)}`, body),
  run: (ref: string) => http.post<ExecutionDetail>(`/benchmarks/${encodeURIComponent(ref)}/run`, { trigger: "ui" }),
  executions: (ref: string, params: { page?: number; page_size?: number } = {}) =>
    http.get<Page<Execution>>(`/benchmarks/${encodeURIComponent(ref)}/executions`, { query: { ...params } }),
  results: (ref: string, params: ResultsParams) =>
    http.get<BenchmarkResults>(`/benchmarks/${encodeURIComponent(ref)}/results`, { query: { ...params } }),
  execution: (id: string) => http.get<ExecutionDetail>(`/benchmark-executions/${id}`),
  cancelExecution: (id: string) => http.post<CancelResult>(`/benchmark-executions/${id}/cancel`),
};

export function useBenchmarks(params: BenchmarkListParams) {
  return useQuery({
    queryKey: queryKeys.list("benchmarks", { ...params }),
    queryFn: () => benchmarksApi.list(params),
    placeholderData: keepPreviousData,
  });
}

export function useBenchmark(ref: string | undefined) {
  return useQuery({
    queryKey: queryKeys.detail("benchmarks", ref ?? ""),
    queryFn: () => benchmarksApi.get(ref as string),
    enabled: Boolean(ref),
  });
}

export function useBenchmarkExecutions(ref: string | undefined, params: { page?: number; page_size?: number } = {}) {
  return useQuery({
    queryKey: queryKeys.sub("benchmarks", ref ?? "", "executions", { ...params }),
    queryFn: () => benchmarksApi.executions(ref as string, params),
    enabled: Boolean(ref),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((e) => isActiveExecution(e.status)) ? LIVE_POLL_MS : false,
  });
}

export function useExecution(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.detail("benchmark-executions", id ?? ""),
    queryFn: () => benchmarksApi.execution(id as string),
    enabled: Boolean(id),
    refetchInterval: (query) => (isActiveExecution(query.state.data?.status) ? LIVE_POLL_MS : false),
  });
}

export function useBenchmarkResults(ref: string | undefined, params: ResultsParams, options: { live?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.sub("benchmarks", ref ?? "", "results", { ...params }),
    queryFn: () => benchmarksApi.results(ref as string, params),
    enabled: Boolean(ref && params.execution_id),
    placeholderData: keepPreviousData,
    refetchInterval: options.live ? LIVE_POLL_MS * 2 : false,
  });
}

export function useCreateBenchmark() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: benchmarksApi.create,
    meta: { silentError: true, successMessage: "Benchmark créé" },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("benchmarks") }),
  });
}

export function useUpdateBenchmark(ref: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BenchmarkUpdateInput) => benchmarksApi.update(ref, body),
    meta: { silentError: true, successMessage: "Benchmark mis à jour" },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("benchmarks") }),
  });
}

export function useRunBenchmark(ref: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => benchmarksApi.run(ref),
    meta: { silentError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("benchmarks") }),
  });
}

export function useCancelExecution() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => benchmarksApi.cancelExecution(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.resource("benchmarks") });
      void qc.invalidateQueries({ queryKey: queryKeys.resource("benchmark-executions") });
    },
  });
}

/* -------------------------------------------------------------------------- */
/* Pickers (read-only platform endpoints)                                     */
/* -------------------------------------------------------------------------- */

const PICKER = "picker";

export const pickersApi = {
  agents: (q?: string) =>
    http.get<Page<AgentListItem>>("/agents", { query: { q, page_size: 100, archived: false } }),
  agentVersion: (id: string) => http.get<AgentVersionDetail>(`/agent-versions/${id}`),
  agentVersions: (agentId: string) => http.get<AgentVersionSummary[]>(`/agents/${agentId}/versions`),
  scenarios: (params: { q?: string; visibility?: string; category?: string }) =>
    http.get<Page<ScenarioListItem>>("/scenarios", { query: { ...params, page_size: 200, archived: false } }),
  scenarioVersions: (scenarioId: string) => http.get<ScenarioVersion[]>(`/scenarios/${scenarioId}/versions`),
  runs: (params: Record<string, string | number | boolean | undefined>) =>
    http.get<Page<RunListItem>>("/runs", { query: params }),
};

export function useAgentOptions(q?: string) {
  return useQuery({
    queryKey: queryKeys.list("agents", { scope: PICKER, q }),
    queryFn: () => pickersApi.agents(q),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useAgentVersionOptions(agentId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.sub("agents", agentId ?? "", "versions", { scope: PICKER }),
    queryFn: () => pickersApi.agentVersions(agentId as string),
    enabled: Boolean(agentId),
    staleTime: 60_000,
  });
}

export function useScenarioOptions(params: { q?: string; visibility?: string; category?: string }) {
  return useQuery({
    queryKey: queryKeys.list("scenarios", { scope: PICKER, ...params }),
    queryFn: () => pickersApi.scenarios(params),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useScenarioVersionOptions(scenarioId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.sub("scenarios", scenarioId ?? "", "versions", { scope: PICKER }),
    queryFn: () => pickersApi.scenarioVersions(scenarioId as string),
    enabled: Boolean(scenarioId),
    staleTime: 60_000,
  });
}

export function useRunsList(params: Record<string, string | number | boolean | undefined>, enabled = true) {
  return useQuery({
    queryKey: queryKeys.list("runs", { scope: PICKER, ...params }),
    queryFn: () => pickersApi.runs(params),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useAgentVersionDetail(id: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.detail("agent-versions", id ?? ""),
    queryFn: () => pickersApi.agentVersion(id as string),
    enabled: Boolean(id),
    staleTime: 5 * 60_000,
  });
}
