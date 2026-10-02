"use client";

/**
 * Runs API (docs/ARCHITECTURE.md §12 — runs [platform] + evaluations [evaluation]):
 * lists, Run Detail, trace, timeline, manifest, scores, verdicts, errors, feedback, provenance,
 * create / cancel / retry / re-evaluate. Also exposes the small reference pickers used by the
 * "Nouveau run" dialog (agents, agent versions, scenarios, evaluation configurations).
 *
 * Every value shown by the UI is computed by the API (composite, gates, verdicts, redaction…).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { TERMINAL_RUN_STATUSES, type RunStatus } from "@/lib/enums";
import { http, type ApiError, type QueryParams } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema, Page } from "./types";

/* -------------------------------------------------------------------------- */
/* Types                                                                      */
/* -------------------------------------------------------------------------- */

export type Run = ApiSchema<"RunOut">;
export type RunDetail = ApiSchema<"RunDetailOut">;
export type RunTrace = ApiSchema<"RunTraceOut">;
export type RunManifest = ApiSchema<"RunManifestOut">;
export type RunScores = ApiSchema<"RunScoresOut">;
export type Score = ApiSchema<"ScoreOut">;
export type Composite = ApiSchema<"CompositeOut">;
export type RunEvaluations = ApiSchema<"RunEvaluationsOut">;
export type Evaluation = ApiSchema<"EvaluationOut">;
export type RunErrors = ApiSchema<"RunErrorsOut">;
export type RunError = ApiSchema<"RunErrorOut">;
export type FeedbackReport = ApiSchema<"FeedbackReportOut">;
export type Provenance = ApiSchema<"ProvenanceOut">;
export type ProvenanceEvaluator = ApiSchema<"ProvenanceEvaluator">;
export type ProvenanceAggregation = ApiSchema<"ProvenanceAggregation">;
export type EvaluateResult = ApiSchema<"EvaluateOut">;
export type RunCreateInput = ApiSchema<"RunCreateIn">;

export type AgentSummary = ApiSchema<"AgentOut">;
export type AgentVersionSummary = ApiSchema<"AgentVersionSummary">;
export type ScenarioSummary = ApiSchema<"ScenarioOut">;
export type EvaluationConfigSummary = ApiSchema<"ConfigOut">;

/** One row of `GET /runs/{id}/timeline` (`forge.domain.traces.timeline.TimelineItem`). */
export interface TimelineItem {
  seq: number;
  id: string | null;
  parent_id: string | null;
  offset_ms: number;
  offset_label: string;
  type: string;
  label: string;
  name: string;
  summary: string;
  duration_ms: number | null;
  status: string;
  depth: number;
  model: string | null;
  tool: string | null;
  agent: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  tokens: number | null;
  cost: number | null;
}

export interface TimelineTypeStat {
  type: string;
  label: string;
  count: number;
  total_duration_ms: number;
  mean_duration_ms: number;
  max_duration_ms: number;
  share: number;
}

export interface TimelineSlowStep {
  seq: number;
  label: string;
  type: string;
  duration_ms: number;
  share: number;
}

/** `GET /runs/{id}/timeline`. */
export interface RunTimeline {
  run_id: string;
  redacted: boolean;
  items: TimelineItem[];
  total_duration_ms?: number | null;
  by_type?: TimelineTypeStat[];
  slowest_steps?: TimelineSlowStep[];
  llm_calls?: number;
  tool_calls?: number;
  errors?: number;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cost?: number | null;
}

/** Full trace event of `GET /runs/{id}/trace` (`events[]`). */
export interface TraceEvent {
  id: string;
  seq: number;
  parent_id: string | null;
  type: string;
  name: string;
  source: string;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  offset_ms: number;
  duration_ms: number | null;
  input: unknown;
  output: unknown;
  attributes: Record<string, unknown> | null;
  span_id: string | null;
  parent_span_id: string | null;
  redacted: boolean;
}

export interface TraceMessage {
  seq?: number;
  role?: string | null;
  content?: unknown;
  name?: string | null;
  offset_ms?: number;
  redacted?: boolean;
}

export interface TraceToolCall {
  seq: number;
  event_id: string;
  tool: string;
  arguments: unknown;
  result: unknown;
  result_seq: number | null;
  status: string;
  duration_ms: number | null;
  offset_ms: number;
  redacted: boolean;
}

export interface TraceModelCall {
  seq: number;
  event_id: string;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost: number | null;
  duration_ms: number | null;
  status: string;
  offset_ms: number;
}

/** `trace` summary inside the Run Detail / trace payloads. */
export interface TraceSummary {
  id?: string;
  started_at?: string | null;
  completed_at?: string | null;
  latency_ms?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
  cost?: number | null;
  model_calls?: number | null;
  tool_calls?: number | null;
  event_count?: number | null;
  errors?: unknown[];
  output_text?: string | null;
  output_json?: unknown;
  redacted?: boolean;
  input?: unknown;
  metadata?: Record<string, unknown>;
}

/** Evidence reference stored on verdicts, errors and recommendations (`EvidenceRef`). */
export interface EvidenceRef {
  excerpt?: string | null;
  location?: string | null;
  trace_event_id?: string | null;
  trace_event_seq?: number | null;
}

/** Composite dimension row (`composite.dimensions[]`). */
export interface CompositeDimension {
  dimension: string;
  value: number | null;
  weight: number | null;
  effective_weight?: number | null;
  criteria?: string[];
}

/** Gate result row (`composite.gates[]`). */
export interface GateResult {
  gate_id: string;
  action: string;
  passed: boolean;
  detail?: string | null;
  cap?: number | null;
}

/** Feedback recommendation (`FeedbackReport.recommendations[]`). */
export interface FeedbackRecommendation {
  title: string;
  category: string;
  priority: string;
  description?: string;
  rationale?: string;
  related_errors?: string[];
  related_criteria?: string[];
  evidence?: EvidenceRef[];
}

/** Error group of a feedback report (`FeedbackReport.errors[]`). */
export interface FeedbackErrorGroup {
  type: string;
  label?: string;
  count: number;
  runs?: number;
  severity: string;
  description?: string;
  examples?: string[];
  criteria?: string[];
  evidence?: EvidenceRef[];
}

/** Individual verdict listed in a provenance aggregation. */
export interface IndividualVerdict {
  evaluation_id: string;
  evaluator_kind: string;
  evaluator_key: string;
  raw_score: number;
  normalized_score: number;
  confidence: number;
  weight?: number | null;
}

/* -------------------------------------------------------------------------- */
/* Typed readers for loosely typed JSON fields                                */
/* -------------------------------------------------------------------------- */

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export const readEvidence = (value: unknown): EvidenceRef[] => asArray<EvidenceRef>(value);
export const readDimensions = (value: unknown): CompositeDimension[] => asArray<CompositeDimension>(value);
export const readGates = (value: unknown): GateResult[] => asArray<GateResult>(value);
export const readRecommendations = (value: unknown): FeedbackRecommendation[] =>
  asArray<FeedbackRecommendation>(value);
export const readFeedbackErrors = (value: unknown): FeedbackErrorGroup[] => asArray<FeedbackErrorGroup>(value);
export const readVerdicts = (value: unknown): IndividualVerdict[] => asArray<IndividualVerdict>(value);
export const readTraceEvents = (trace: RunTrace | undefined): TraceEvent[] =>
  asArray<TraceEvent>(trace?.events);
export const readMessages = (trace: RunTrace | undefined): TraceMessage[] => asArray<TraceMessage>(trace?.messages);
export const readToolCalls = (trace: RunTrace | undefined): TraceToolCall[] =>
  asArray<TraceToolCall>(trace?.tool_calls);
export const readModelCalls = (trace: RunTrace | undefined): TraceModelCall[] =>
  asArray<TraceModelCall>(trace?.model_calls);
export const readTraceSummary = (value: unknown): TraceSummary | null =>
  value && typeof value === "object" ? (value as TraceSummary) : null;

/** True while the run still changes on the server (polling). */
export function isRunActive(status: string | null | undefined): boolean {
  return Boolean(status) && !TERMINAL_RUN_STATUSES.has(status as RunStatus);
}

/** Polling cadence while a run is pending / running / evaluating. */
export const RUN_POLL_MS = 2500;

/* -------------------------------------------------------------------------- */
/* List filters                                                               */
/* -------------------------------------------------------------------------- */

export type RunSort = "-created_at" | "created_at" | "-composite" | "composite" | "-latency" | "latency";

export interface RunListParams {
  page?: number;
  page_size?: number;
  status?: string[];
  origin?: string;
  agent_id?: string;
  agent_version_id?: string;
  scenario_id?: string;
  benchmark_execution_id?: string;
  experiment_id?: string;
  passed?: boolean;
  gate_failed?: boolean;
  min_composite?: number;
  max_composite?: number;
  created_from?: string;
  created_to?: string;
  q?: string;
  sort?: RunSort;
}

function toQuery(params: RunListParams): QueryParams {
  return { ...params } as QueryParams;
}

/* -------------------------------------------------------------------------- */
/* Raw calls                                                                  */
/* -------------------------------------------------------------------------- */

const roundQuery = (round?: number | null): QueryParams => (round ? { round } : {});

export const runsApi = {
  list: (params: RunListParams, signal?: AbortSignal) =>
    http.get<Page<Run>>("/runs", { query: toQuery(params), signal }),
  get: (id: string, signal?: AbortSignal) => http.get<RunDetail>(`/runs/${id}`, { signal }),
  trace: (id: string, signal?: AbortSignal) => http.get<RunTrace>(`/runs/${id}/trace`, { signal }),
  timeline: (id: string, signal?: AbortSignal) => http.get<RunTimeline>(`/runs/${id}/timeline`, { signal }),
  manifest: (id: string, signal?: AbortSignal) => http.get<RunManifest>(`/runs/${id}/manifest`, { signal }),
  scores: (id: string, round?: number | null, signal?: AbortSignal) =>
    http.get<RunScores>(`/runs/${id}/scores`, { query: roundQuery(round), signal }),
  evaluations: (id: string, round?: number | null, signal?: AbortSignal) =>
    http.get<RunEvaluations>(`/runs/${id}/evaluations`, { query: roundQuery(round), signal }),
  errors: (id: string, round?: number | null, signal?: AbortSignal) =>
    http.get<RunErrors>(`/runs/${id}/errors`, { query: roundQuery(round), signal }),
  feedback: (id: string, round?: number | null, signal?: AbortSignal) =>
    http.get<FeedbackReport>(`/runs/${id}/feedback`, { query: roundQuery(round), signal }),
  provenance: (id: string, criterionKey: string, round?: number | null, signal?: AbortSignal) =>
    http.get<Provenance>(`/runs/${id}/scores/${encodeURIComponent(criterionKey)}/provenance`, {
      query: roundQuery(round),
      signal,
    }),
  create: (body: RunCreateInput) => http.post<Run[]>("/runs", body),
  cancel: (id: string) => http.post<Run>(`/runs/${id}/cancel`),
  retry: (id: string) => http.post<Run>(`/runs/${id}/retry`),
  evaluate: (id: string, evaluationConfigId?: string | null) =>
    http.post<EvaluateResult>(`/runs/${id}/evaluate`, { evaluation_config_id: evaluationConfigId ?? null }),

  // Reference pickers (other modules' endpoints, read-only use here).
  agents: (q?: string) => http.get<Page<AgentSummary>>("/agents", { query: { page_size: 200, q } }),
  agentVersions: (agentId: string) => http.get<AgentVersionSummary[]>(`/agents/${agentId}/versions`),
  scenarios: (q?: string) =>
    http.get<Page<ScenarioSummary>>("/scenarios", { query: { page_size: 200, q } }),
  evaluationConfigs: () =>
    http.get<Page<EvaluationConfigSummary>>("/evaluation-configs", { query: { page_size: 200, latest_only: true } }),
};

/* -------------------------------------------------------------------------- */
/* Hooks                                                                      */
/* -------------------------------------------------------------------------- */

/** Runs list; polls while at least one visible run is not terminal. */
export function useRuns(params: RunListParams) {
  return useQuery<Page<Run>, ApiError>({
    queryKey: queryKeys.list("runs", toQuery(params)),
    queryFn: ({ signal }) => runsApi.list(params, signal),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((r) => isRunActive(r.status)) ? RUN_POLL_MS * 2 : false,
  });
}

/** Run Detail; polls while the run is pending / running / evaluating. */
export function useRun(id: string) {
  return useQuery<RunDetail, ApiError>({
    queryKey: queryKeys.detail("runs", id),
    queryFn: ({ signal }) => runsApi.get(id, signal),
    refetchInterval: (query) => (isRunActive(query.state.data?.status) ? RUN_POLL_MS : false),
  });
}

interface LiveOptions {
  /** Poll while the parent run is active. */
  live?: boolean;
  enabled?: boolean;
}

export function useRunTimeline(id: string, { live = false, enabled = true }: LiveOptions = {}) {
  return useQuery<RunTimeline, ApiError>({
    queryKey: queryKeys.sub("runs", id, "timeline"),
    queryFn: ({ signal }) => runsApi.timeline(id, signal),
    refetchInterval: live ? RUN_POLL_MS : false,
    enabled,
  });
}

export function useRunTrace(id: string, { live = false, enabled = true }: LiveOptions = {}) {
  return useQuery<RunTrace, ApiError>({
    queryKey: queryKeys.sub("runs", id, "trace"),
    queryFn: ({ signal }) => runsApi.trace(id, signal),
    refetchInterval: live ? RUN_POLL_MS : false,
    enabled,
  });
}

export function useRunManifest(id: string, enabled: boolean) {
  return useQuery<RunManifest, ApiError>({
    queryKey: queryKeys.sub("runs", id, "manifest"),
    queryFn: ({ signal }) => runsApi.manifest(id, signal),
    enabled,
    staleTime: Infinity,
  });
}

export function useRunScores(id: string, round: number | null, { live = false, enabled = true }: LiveOptions = {}) {
  return useQuery<RunScores, ApiError>({
    queryKey: queryKeys.sub("runs", id, "scores", { round }),
    queryFn: ({ signal }) => runsApi.scores(id, round, signal),
    refetchInterval: live ? RUN_POLL_MS : false,
    enabled,
  });
}

export function useRunEvaluations(id: string, round: number | null, { live = false, enabled = true }: LiveOptions = {}) {
  return useQuery<RunEvaluations, ApiError>({
    queryKey: queryKeys.sub("runs", id, "evaluations", { round }),
    queryFn: ({ signal }) => runsApi.evaluations(id, round, signal),
    refetchInterval: live ? RUN_POLL_MS : false,
    enabled,
  });
}

export function useRunErrors(id: string, round: number | null, { live = false, enabled = true }: LiveOptions = {}) {
  return useQuery<RunErrors, ApiError>({
    queryKey: queryKeys.sub("runs", id, "errors", { round }),
    queryFn: ({ signal }) => runsApi.errors(id, round, signal),
    refetchInterval: live ? RUN_POLL_MS : false,
    enabled,
  });
}

export function useRunFeedback(id: string, round: number | null, { live = false, enabled = true }: LiveOptions = {}) {
  return useQuery<FeedbackReport, ApiError>({
    queryKey: queryKeys.sub("runs", id, "feedback", { round }),
    queryFn: ({ signal }) => runsApi.feedback(id, round, signal),
    refetchInterval: live ? RUN_POLL_MS * 2 : false,
    enabled,
    retry: false,
  });
}

export function useScoreProvenance(id: string, criterionKey: string | null, round: number | null) {
  return useQuery<Provenance, ApiError>({
    queryKey: queryKeys.sub("runs", id, `provenance:${criterionKey ?? ""}`, { round }),
    queryFn: ({ signal }) => runsApi.provenance(id, criterionKey ?? "", round, signal),
    enabled: Boolean(criterionKey),
  });
}

/** Refresh every query of one run (detail + sub-resources) and the runs lists. */
function useInvalidateRun() {
  const qc = useQueryClient();
  return (id?: string) => {
    if (id) void qc.invalidateQueries({ queryKey: queryKeys.detail("runs", id) });
    void qc.invalidateQueries({ queryKey: [...queryKeys.resource("runs"), "list"] });
  };
}

export function useCreateRuns() {
  const invalidate = useInvalidateRun();
  return useMutation<Run[], ApiError, RunCreateInput>({
    mutationFn: runsApi.create,
    meta: { silentError: true },
    onSuccess: () => invalidate(),
  });
}

export function useCancelRun(id: string) {
  const invalidate = useInvalidateRun();
  return useMutation<Run, ApiError, void>({
    mutationFn: () => runsApi.cancel(id),
    meta: { successMessage: "Run annulé." },
    onSuccess: () => invalidate(id),
  });
}

export function useRetryRun(id: string) {
  const invalidate = useInvalidateRun();
  return useMutation<Run, ApiError, void>({
    mutationFn: () => runsApi.retry(id),
    meta: { successMessage: "Nouvel essai lancé." },
    onSuccess: () => invalidate(id),
  });
}

export function useEvaluateRun(id: string) {
  const invalidate = useInvalidateRun();
  return useMutation<EvaluateResult, ApiError, { evaluationConfigId?: string | null }>({
    mutationFn: ({ evaluationConfigId }) => runsApi.evaluate(id, evaluationConfigId),
    meta: { silentError: true },
    onSuccess: () => invalidate(id),
  });
}

/* Pickers ------------------------------------------------------------------ */

export function useAgentOptions(enabled = true) {
  return useQuery<Page<AgentSummary>, ApiError>({
    queryKey: queryKeys.list("agents", { page_size: 200, picker: "runs" }),
    queryFn: () => runsApi.agents(),
    enabled,
    staleTime: 60_000,
  });
}

export function useAgentVersionOptions(agentId: string | null | undefined) {
  return useQuery<AgentVersionSummary[], ApiError>({
    queryKey: queryKeys.sub("agents", agentId ?? "", "versions", { picker: "runs" }),
    queryFn: () => runsApi.agentVersions(agentId ?? ""),
    enabled: Boolean(agentId),
    staleTime: 60_000,
  });
}

export function useScenarioOptions(enabled = true) {
  return useQuery<Page<ScenarioSummary>, ApiError>({
    queryKey: queryKeys.list("scenarios", { page_size: 200, picker: "runs" }),
    queryFn: () => runsApi.scenarios(),
    enabled,
    staleTime: 60_000,
  });
}

export function useEvaluationConfigOptions(enabled = true) {
  return useQuery<Page<EvaluationConfigSummary>, ApiError>({
    queryKey: queryKeys.list("evaluation-configs", { page_size: 200, latest_only: true, picker: "runs" }),
    queryFn: () => runsApi.evaluationConfigs(),
    enabled,
    staleTime: 60_000,
  });
}
