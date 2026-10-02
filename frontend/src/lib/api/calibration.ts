"use client";

/** Calibration API (docs/ARCHITECTURE.md §9.4): `GET /calibration?judge_id=&criterion_key=&dataset_id=`. */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { http, type ApiError } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema, Page } from "./types";

export type CalibrationReport = ApiSchema<"CalibrationOut">;
export type CalibrationMetrics = ApiSchema<"CalibrationMetricsOut">;
export type ScorePair = ApiSchema<"ScorePairOut">;
export type JudgeSummary = ApiSchema<"JudgeOut">;

export interface CalibrationParams {
  judge_id?: string;
  criterion_key?: string;
  dataset_id?: string;
}

export const calibrationApi = {
  report: (params: CalibrationParams, signal?: AbortSignal) =>
    http.get<CalibrationReport>("/calibration", { query: { ...params }, signal }),
  judges: () => http.get<Page<JudgeSummary>>("/judges", { query: { page_size: 200, latest_only: false } }),
};

export function useCalibration(params: CalibrationParams) {
  return useQuery<CalibrationReport, ApiError>({
    queryKey: queryKeys.list("calibration", { ...params }),
    queryFn: ({ signal }) => calibrationApi.report(params, signal),
    placeholderData: keepPreviousData,
  });
}

/** Every judge version (calibration is computed per judge version). */
export function useJudgeOptions() {
  return useQuery<Page<JudgeSummary>, ApiError>({
    queryKey: queryKeys.list("judges", { page_size: 200, latest_only: false, picker: "calibration" }),
    queryFn: () => calibrationApi.judges(),
    staleTime: 60_000,
  });
}
