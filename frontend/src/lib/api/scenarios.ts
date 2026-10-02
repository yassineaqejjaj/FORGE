"use client";

/**
 * Scenario Manager API (`/scenarios`, `/scenario-versions`, import / export) and the `/meta`
 * vocabulary (rule catalog, adapters, criteria, categories) — docs/ARCHITECTURE.md §3.3, §6, §12.
 * Redaction of private content is decided by the API (`redacted: true`).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiUrl, http, saveBlob, type QueryParams } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema, Page } from "./types";

export type Meta = ApiSchema<"MetaOut">;
export type MetaRuleType = ApiSchema<"RuleTypeOut">;
export type MetaAdapter = ApiSchema<"AdapterKindOut">;
export type MetaCriterion = ApiSchema<"MetaCriterion">;
export type MetaErrorType = ApiSchema<"MetaErrorType">;

export type Scenario = ApiSchema<"ScenarioOut">;
export type ScenarioDetail = ApiSchema<"ScenarioDetailOut">;
export type ScenarioVersion = ApiSchema<"ScenarioVersionOut">;
export type ScenarioVersionSummary = ApiSchema<"ScenarioVersionSummary">;
export type ScenarioContentInput = ApiSchema<"ScenarioContentIn">;
export type ScenarioCreateInput = ApiSchema<"ScenarioCreateIn">;
export type ScenarioUpdateInput = ApiSchema<"ScenarioUpdateIn">;
export type ScenarioVersionCreateInput = ApiSchema<"ScenarioVersionCreateIn">;
export type VariantCreateInput = ApiSchema<"VariantCreateIn">;
export type FamilyMember = ApiSchema<"FamilyMember">;
export type ImportReport = ApiSchema<"ImportReportOut">;

export interface ScenarioListParams {
  q?: string;
  category?: string;
  visibility?: string;
  difficulty?: string;
  tag?: string;
  family?: string;
  /** false (default, active) or true (archived only). */
  archived?: boolean;
  page?: number;
  page_size?: number;
}

export interface ScenarioExportParams {
  format: "yaml" | "json";
  versions?: "all" | "latest";
  ids?: string[];
  q?: string;
  category?: string;
  visibility?: string;
  tag?: string;
  archived?: boolean;
}

export interface ExportResult {
  filename: string;
  skippedPrivate: number;
  hiddenRulesRemoved: number;
}

async function exportScenarios(params: ScenarioExportParams): Promise<ExportResult> {
  const query: QueryParams = { ...params };
  let response: Response;
  try {
    response = await fetch(apiUrl("/scenarios/export", query), { credentials: "include", cache: "no-store" });
  } catch {
    throw new ApiError({ status: 0, code: "network_error", detail: "Impossible de joindre le serveur FORGE." });
  }
  if (!response.ok) {
    let detail = "L'export a échoué.";
    let code = "export_failed";
    try {
      const body = (await response.json()) as { detail?: unknown; code?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      if (typeof body.code === "string") code = body.code;
    } catch {
      // keep the default message
    }
    throw new ApiError({ status: response.status, code, detail });
  }
  const filename = `forge-scenarios.${params.format}`;
  saveBlob(await response.blob(), filename);
  return {
    filename,
    skippedPrivate: Number(response.headers.get("x-forge-skipped-private") ?? 0) || 0,
    hiddenRulesRemoved: Number(response.headers.get("x-forge-hidden-rules-removed") ?? 0) || 0,
  };
}

export const scenariosApi = {
  meta: (signal?: AbortSignal) => http.get<Meta>("/meta", { signal }),
  list: (params: ScenarioListParams, signal?: AbortSignal) =>
    http.get<Page<Scenario>>("/scenarios", { query: { ...params }, signal }),
  get: (id: string, signal?: AbortSignal) => http.get<ScenarioDetail>(`/scenarios/${id}`, { signal }),
  create: (body: ScenarioCreateInput) => http.post<ScenarioDetail>("/scenarios", body),
  update: (id: string, body: ScenarioUpdateInput) => http.patch<ScenarioDetail>(`/scenarios/${id}`, body),
  versions: (id: string, signal?: AbortSignal) => http.get<ScenarioVersion[]>(`/scenarios/${id}/versions`, { signal }),
  createVersion: (id: string, body: ScenarioVersionCreateInput) =>
    http.post<ScenarioVersion>(`/scenarios/${id}/versions`, body),
  version: (versionId: string, signal?: AbortSignal) =>
    http.get<ScenarioVersion>(`/scenario-versions/${versionId}`, { signal }),
  createVariant: (id: string, body: VariantCreateInput) => http.post<ScenarioDetail>(`/scenarios/${id}/variants`, body),
  import: (file: File, dryRun: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", dryRun ? "true" : "false");
    return http.upload<ImportReport>("/scenarios/import", form, { query: { dry_run: dryRun } });
  },
  export: exportScenarios,
};

/** `GET /meta` — vocabularies with French labels (cached for the session). */
export function useMeta() {
  return useQuery({
    queryKey: queryKeys.meta(),
    queryFn: ({ signal }) => scenariosApi.meta(signal),
    staleTime: 30 * 60_000,
  });
}

export function useScenarios(params: ScenarioListParams) {
  return useQuery({
    queryKey: queryKeys.list("scenarios", { ...params }),
    queryFn: ({ signal }) => scenariosApi.list(params, signal),
    placeholderData: keepPreviousData,
  });
}

export function useScenario(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.detail("scenarios", id ?? ""),
    queryFn: ({ signal }) => scenariosApi.get(id!, signal),
    enabled: Boolean(id),
  });
}

/** Every version of a scenario with its (possibly redacted) content. */
export function useScenarioVersions(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.sub("scenarios", id ?? "", "versions"),
    queryFn: ({ signal }) => scenariosApi.versions(id!, signal),
    enabled: Boolean(id) && enabled,
  });
}

function useInvalidateScenarios() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: queryKeys.resource("scenarios") });
}

export function useCreateScenario() {
  const invalidate = useInvalidateScenarios();
  return useMutation<ScenarioDetail, ApiError, ScenarioCreateInput>({
    mutationFn: scenariosApi.create,
    meta: { silentError: true },
    onSuccess: invalidate,
  });
}

export function useUpdateScenario(id: string) {
  const qc = useQueryClient();
  return useMutation<ScenarioDetail, ApiError, ScenarioUpdateInput>({
    mutationFn: (body) => scenariosApi.update(id, body),
    meta: { silentError: true },
    onSuccess: (detail) => {
      qc.setQueryData(queryKeys.detail("scenarios", id), detail);
      void qc.invalidateQueries({ queryKey: queryKeys.resource("scenarios") });
    },
  });
}

export function useCreateScenarioVersion(id: string) {
  const invalidate = useInvalidateScenarios();
  return useMutation<ScenarioVersion, ApiError, ScenarioVersionCreateInput>({
    mutationFn: (body) => scenariosApi.createVersion(id, body),
    meta: { silentError: true },
    onSuccess: invalidate,
  });
}

export function useCreateVariant(id: string) {
  const invalidate = useInvalidateScenarios();
  return useMutation<ScenarioDetail, ApiError, VariantCreateInput>({
    mutationFn: (body) => scenariosApi.createVariant(id, body),
    meta: { silentError: true },
    onSuccess: invalidate,
  });
}

export function useImportScenarios() {
  const invalidate = useInvalidateScenarios();
  return useMutation<ImportReport, ApiError, { file: File; dryRun: boolean }>({
    mutationFn: ({ file, dryRun }) => scenariosApi.import(file, dryRun),
    meta: { silentError: true },
    onSuccess: (report) => {
      if (!report.dry_run) invalidate();
    },
  });
}

export function useExportScenarios() {
  return useMutation<ExportResult, ApiError, ScenarioExportParams>({
    mutationFn: scenariosApi.export,
  });
}
