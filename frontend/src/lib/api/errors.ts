"use client";

/** Errors explorer API (docs/ARCHITECTURE.md §12 — analytics): `GET /errors` (filters + aggregations). */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { http, type ApiError } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema } from "./types";

export type ErrorsPage = ApiSchema<"ErrorsPageOut">;
export type ErrorItem = ApiSchema<"ErrorItemOut">;
export type ErrorAggregations = ApiSchema<"ErrorAggregationsOut">;
export type ErrorTypeDef = ApiSchema<"ErrorTypeOut">;

export interface ErrorsParams {
  page?: number;
  page_size?: number;
  error_type?: string[];
  severity?: string[];
  agent_id?: string;
  agent_version_id?: string;
  scenario_id?: string;
  category?: string;
  benchmark_execution_id?: string;
  experiment_id?: string;
  run_id?: string;
  date_from?: string;
  date_to?: string;
}

export const errorsApi = {
  explore: (params: ErrorsParams, signal?: AbortSignal) =>
    http.get<ErrorsPage>("/errors", { query: { ...params }, signal }),
  types: () => http.get<ErrorTypeDef[]>("/error-types"),
};

export function useErrorsExplorer(params: ErrorsParams) {
  return useQuery<ErrorsPage, ApiError>({
    queryKey: queryKeys.list("errors", { ...params }),
    queryFn: ({ signal }) => errorsApi.explore(params, signal),
    placeholderData: keepPreviousData,
  });
}

export function useErrorTypes() {
  return useQuery<ErrorTypeDef[], ApiError>({
    queryKey: queryKeys.list("error-types"),
    queryFn: () => errorsApi.types(),
    staleTime: 5 * 60_000,
  });
}
