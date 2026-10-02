"use client";

/**
 * Evaluation configurations API (docs/ARCHITECTURE.md §7.4–7.5, §12): ScoreConfiguration versions
 * (dimension / criterion weights, normalisation, gates, pinned judges, aggregation, threshold) and
 * previews (recomputed composites, nothing persisted). Also exposes `GET /meta` (vocabularies).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema, Page } from "./types";

export type EvaluationConfig = ApiSchema<"ConfigOut">;
export type EvaluationConfigDetail = ApiSchema<"ConfigDetailOut">;
export type ConfigJudge = ApiSchema<"ConfigJudgeOut">;
export type ConfigVersionSummary = ApiSchema<"ConfigVersionSummary">;
export type ConfigCreateInput = ApiSchema<"ConfigCreateIn">;
export type ConfigVersionInput = ApiSchema<"ConfigVersionIn">;
export type ConfigBehaviourInput = ApiSchema<"ConfigBehaviourIn">;
export type PreviewInput = ApiSchema<"PreviewIn">;
export type PreviewResult = ApiSchema<"PreviewOut">;
export type PreviewItem = ApiSchema<"PreviewItemOut">;
export type ForgeMeta = ApiSchema<"MetaOut">;
export type MetaCriterion = ApiSchema<"MetaCriterion">;

/** Gate specification (`GateSpec`, stored as JSON in `gates[]`). */
export interface GateSpecValue {
  id: string;
  kind: "dimension" | "criterion" | "error" | "rule";
  target: string;
  action: "fail" | "cap";
  min?: number | null;
  min_severity?: string | null;
  cap?: number | null;
  description?: string;
}

/** Normalisation targets (`NormalizationSpec`). */
export interface NormalizationValue {
  cost_target?: number;
  cost_max?: number;
  latency_target_ms?: number;
  latency_max_ms?: number;
  robustness_max_std?: number;
}

/** Aggregation (`AggregationSpec`). */
export interface AggregationValue {
  method: string;
  weights?: Record<string, number>;
  expression?: string | null;
}

export interface ConfigListParams {
  page?: number;
  page_size?: number;
  q?: string;
  latest_only?: boolean;
  key?: string;
}

export const evaluationConfigsApi = {
  list: (params: ConfigListParams = {}) =>
    http.get<Page<EvaluationConfig>>("/evaluation-configs", { query: { ...params } }),
  get: (id: string) => http.get<EvaluationConfigDetail>(`/evaluation-configs/${id}`),
  create: (body: ConfigCreateInput) => http.post<EvaluationConfigDetail>("/evaluation-configs", body),
  createVersion: (id: string, body: ConfigVersionInput) =>
    http.post<EvaluationConfigDetail>(`/evaluation-configs/${id}/versions`, body),
  preview: (id: string, body: PreviewInput) => http.post<PreviewResult>(`/evaluation-configs/${id}/preview`, body),
  meta: () => http.get<ForgeMeta>("/meta"),
};

/** `GET /meta` — vocabularies, criteria, error types, capabilities (cached for the session). */
export function useForgeMeta() {
  return useQuery({
    queryKey: queryKeys.meta(),
    queryFn: evaluationConfigsApi.meta,
    staleTime: 30 * 60_000,
  });
}

export function useEvaluationConfigs(params: ConfigListParams = {}) {
  return useQuery({
    queryKey: queryKeys.list("evaluation-configs", { ...params }),
    queryFn: () => evaluationConfigsApi.list(params),
    placeholderData: keepPreviousData,
  });
}

export function useEvaluationConfig(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.detail("evaluation-configs", id ?? ""),
    queryFn: () => evaluationConfigsApi.get(id as string),
    enabled: Boolean(id),
  });
}

export function useCreateEvaluationConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: evaluationConfigsApi.create,
    meta: { silentError: true, successMessage: "Configuration créée" },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("evaluation-configs") }),
  });
}

export function useCreateEvaluationConfigVersion(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ConfigVersionInput) => evaluationConfigsApi.createVersion(id, body),
    meta: { silentError: true, successMessage: "Nouvelle version de la configuration créée" },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("evaluation-configs") }),
  });
}

export function usePreviewEvaluationConfig(id: string) {
  return useMutation({
    mutationFn: (body: PreviewInput) => evaluationConfigsApi.preview(id, body),
    meta: { silentError: true },
  });
}
