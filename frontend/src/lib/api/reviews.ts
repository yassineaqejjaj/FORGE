"use client";

/**
 * Human review API (docs/ARCHITECTURE.md §9.4, §12 — reviews [platform]):
 * `GET /reviews/queue`, `GET|POST /runs/{id}/human-evaluations`, gold datasets and criteria catalog.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http, type ApiError } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema, Page } from "./types";

export type ReviewQueueItem = ApiSchema<"ReviewQueueItem">;
export type ReviewCriterion = ApiSchema<"ReviewCriterion">;
export type HumanEvaluation = ApiSchema<"HumanEvaluationOut">;
export type HumanEvaluationInput = ApiSchema<"HumanEvaluationIn">;
export type HumanEvaluationSubmitResult = ApiSchema<"HumanEvaluationSubmitOut">;
export type Dataset = ApiSchema<"DatasetOut">;
export type Criterion = ApiSchema<"CriterionOut">;

export interface ReviewQueueParams {
  page?: number;
  page_size?: number;
  dataset_id?: string;
  blind?: boolean;
}

export const reviewsApi = {
  queue: (params: ReviewQueueParams, signal?: AbortSignal) =>
    http.get<Page<ReviewQueueItem>>("/reviews/queue", { query: { ...params }, signal }),
  humanEvaluations: (runId: string, signal?: AbortSignal) =>
    http.get<HumanEvaluation[]>(`/runs/${runId}/human-evaluations`, { signal }),
  submit: (runId: string, body: HumanEvaluationInput) =>
    http.post<HumanEvaluationSubmitResult>(`/runs/${runId}/human-evaluations`, body),
  goldDatasets: () => http.get<Page<Dataset>>("/datasets", { query: { kind: "gold", page_size: 200 } }),
  criteria: () => http.get<Criterion[]>("/criteria"),
};

export function useReviewQueue(params: ReviewQueueParams, enabled = true) {
  return useQuery<Page<ReviewQueueItem>, ApiError>({
    queryKey: queryKeys.list("reviews", { ...params }),
    queryFn: ({ signal }) => reviewsApi.queue(params, signal),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useHumanEvaluations(runId: string, enabled = true) {
  return useQuery<HumanEvaluation[], ApiError>({
    queryKey: queryKeys.sub("runs", runId, "human-evaluations"),
    queryFn: ({ signal }) => reviewsApi.humanEvaluations(runId, signal),
    enabled,
  });
}

/** Submit (or replace) the current user's human evaluation, then refresh the run and the queue. */
export function useSubmitHumanEvaluation(runId: string) {
  const qc = useQueryClient();
  return useMutation<HumanEvaluationSubmitResult, ApiError, HumanEvaluationInput>({
    mutationFn: (body) => reviewsApi.submit(runId, body),
    meta: { silentError: true, successMessage: "Évaluation humaine enregistrée." },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.detail("runs", runId) });
      void qc.invalidateQueries({ queryKey: queryKeys.resource("reviews") });
      void qc.invalidateQueries({ queryKey: queryKeys.resource("calibration") });
      void qc.invalidateQueries({ queryKey: [...queryKeys.resource("runs"), "list"] });
    },
  });
}

export function useGoldDatasets(enabled = true) {
  return useQuery<Page<Dataset>, ApiError>({
    queryKey: queryKeys.list("datasets", { kind: "gold", page_size: 200 }),
    queryFn: () => reviewsApi.goldDatasets(),
    enabled,
    staleTime: 60_000,
  });
}

export function useCriteriaCatalog(enabled = true) {
  return useQuery<Criterion[], ApiError>({
    queryKey: queryKeys.list("criteria"),
    queryFn: () => reviewsApi.criteria(),
    enabled,
    staleTime: 5 * 60_000,
  });
}
