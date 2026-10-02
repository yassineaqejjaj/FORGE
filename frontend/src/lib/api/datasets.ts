"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http, type ApiError } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema, Page } from "./types";

export type Dataset = ApiSchema<"DatasetOut">;
export type DatasetDetail = ApiSchema<"DatasetDetailOut">;
export type DatasetItem = ApiSchema<"DatasetItemOut">;
export type DatasetCreate = ApiSchema<"DatasetCreateIn">;
export type DatasetKind = Dataset["kind"];

export interface DatasetListParams {
  page?: number;
  page_size?: number;
  kind?: DatasetKind;
  q?: string;
}

export function useDatasets(params: DatasetListParams) {
  return useQuery<Page<Dataset>, ApiError>({
    queryKey: queryKeys.list("datasets", { ...params }),
    queryFn: ({ signal }) => http.get<Page<Dataset>>("/datasets", { query: { ...params }, signal }),
    staleTime: 30_000,
  });
}

export function useDataset(id: string) {
  return useQuery<DatasetDetail, ApiError>({
    queryKey: queryKeys.detail("datasets", id),
    queryFn: ({ signal }) => http.get<DatasetDetail>(`/datasets/${id}`, { signal }),
    enabled: Boolean(id),
  });
}

export function useCreateDataset() {
  const qc = useQueryClient();
  return useMutation<DatasetDetail, ApiError, DatasetCreate>({
    mutationFn: (body) => http.post<DatasetDetail>("/datasets", body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.resource("datasets") });
    },
  });
}

export const DATASET_KIND_META: Record<DatasetKind, { label: string; description: string }> = {
  context: { label: "Contexte", description: "Documents fournis aux agents par les scénarios" },
  gold: { label: "Gold", description: "Exécutions de référence notées par des humains (calibration des juges)" },
};
