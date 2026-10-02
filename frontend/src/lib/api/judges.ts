"use client";

/**
 * Judges API (docs/ARCHITECTURE.md §7.3, §12): immutable judge versions (key + version), enabling,
 * dry-run test on an existing run, calibration status (§9.4).
 * Reads: viewer · writes and tests: maintainer.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema, Page } from "./types";

export type Judge = ApiSchema<"JudgeOut">;
export type JudgeDetail = ApiSchema<"JudgeDetailOut">;
export type JudgeVersionSummary = ApiSchema<"JudgeVersionSummary">;
export type JudgeCreateInput = ApiSchema<"JudgeCreateIn">;
export type JudgeVersionInput = ApiSchema<"JudgeVersionIn">;
export type JudgeUpdateInput = ApiSchema<"JudgeUpdateIn">;
export type JudgeTestInput = ApiSchema<"JudgeTestIn">;
export type JudgeTestResult = ApiSchema<"JudgeTestOut">;
export type Calibration = ApiSchema<"CalibrationOut">;
export type CalibrationMetrics = ApiSchema<"CalibrationMetricsOut">;

/** One verdict of `POST /judges/{id}/test` (`verdicts[]` is untyped in the OpenAPI schema). */
export interface JudgeTestVerdict {
  criterion_key: string;
  dimension?: string;
  raw_score?: number | null;
  scale_min?: number;
  scale_max?: number;
  normalized_score?: number | null;
  confidence?: number | null;
  explanation?: string;
  evidence?: Array<{ excerpt?: string; event?: number | null; location?: string; [key: string]: unknown }>;
  errors?: Array<{ type?: string; error_type?: string; severity?: string; description?: string; [key: string]: unknown }>;
}

export interface JudgeListParams {
  page?: number;
  page_size?: number;
  provider?: string;
  enabled?: boolean;
  q?: string;
  latest_only?: boolean;
  key?: string;
}

export const judgesApi = {
  list: (params: JudgeListParams = {}) => http.get<Page<Judge>>("/judges", { query: { ...params } }),
  get: (id: string) => http.get<JudgeDetail>(`/judges/${id}`),
  create: (body: JudgeCreateInput) => http.post<JudgeDetail>("/judges", body),
  createVersion: (id: string, body: JudgeVersionInput) => http.post<JudgeDetail>(`/judges/${id}/versions`, body),
  update: (id: string, body: JudgeUpdateInput) => http.patch<JudgeDetail>(`/judges/${id}`, body),
  test: (id: string, body: JudgeTestInput) => http.post<JudgeTestResult>(`/judges/${id}/test`, body),
  calibration: (params: { judge_id?: string } = {}) => http.get<Calibration>("/calibration", { query: { ...params } }),
};

export function useJudges(params: JudgeListParams) {
  return useQuery({
    queryKey: queryKeys.list("judges", { ...params }),
    queryFn: () => judgesApi.list(params),
    placeholderData: keepPreviousData,
  });
}

export function useJudge(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.detail("judges", id ?? ""),
    queryFn: () => judgesApi.get(id as string),
    enabled: Boolean(id),
  });
}

/** Global calibration (by_judge rows carry the status per judge key). */
export function useJudgesCalibration(params: { judge_id?: string } = {}) {
  return useQuery({
    queryKey: queryKeys.list("calibration", { scope: "judges", ...params }),
    queryFn: () => judgesApi.calibration(params),
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useCreateJudge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: judgesApi.create,
    meta: { silentError: true, successMessage: "Juge créé" },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("judges") }),
  });
}

export function useCreateJudgeVersion(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: JudgeVersionInput) => judgesApi.createVersion(id, body),
    meta: { silentError: true, successMessage: "Nouvelle version du juge créée" },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("judges") }),
  });
}

export function useUpdateJudge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: JudgeUpdateInput }) => judgesApi.update(id, body),
    meta: { silentError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("judges") }),
  });
}

export function useTestJudge(id: string) {
  return useMutation({
    mutationFn: (body: JudgeTestInput) => judgesApi.test(id, body),
    meta: { silentError: true },
  });
}

/** French descriptions of the rubric placeholders (`JudgeDetailOut.placeholders`). */
export const PLACEHOLDER_HELP: Record<string, string> = {
  scenario_name: "Nom du scénario",
  scenario_description: "Description du scénario",
  category: "Catégorie du scénario",
  difficulty: "Difficulté",
  input: "Demande reçue par l'agent",
  context: "Contexte fourni à l'agent (documents…)",
  constraints: "Contraintes à respecter",
  expected_output: "Résultat attendu (non visible par l'agent)",
  expected_behavior: "Comportement attendu",
  output: "Sortie finale de l'agent",
  trace: "Trace compactée ([E<seq>] +<offset>ms type nom — résumé)",
  criteria: "Critères à évaluer (question, échelle)",
  error_types: "Taxonomie des erreurs",
};
