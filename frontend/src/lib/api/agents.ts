"use client";

/**
 * Agent Registry API (`/agents`, `/agent-versions`) — docs/ARCHITECTURE.md §6, §12.
 * Versions are immutable: "editing" an agent's behaviour always creates a new version
 * (identical content → 409 conflict, computed by the API).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http, type ApiError } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema, Page } from "./types";

export type Agent = ApiSchema<"AgentOut">;
export type AgentCreateInput = ApiSchema<"AgentCreateIn">;
export type AgentUpdateInput = ApiSchema<"AgentUpdateIn">;
export type AgentVersionSummary = ApiSchema<"AgentVersionSummary">;
export type AgentVersion = ApiSchema<"AgentVersionOut">;
export type AgentVersionCreateInput = ApiSchema<"AgentVersionCreateIn">;
export type AgentVersionDiff = ApiSchema<"AgentVersionDiffOut">;
export type AgentTestInput = ApiSchema<"AgentTestIn">;
export type AgentTestOutput = ApiSchema<"AgentTestOut">;
export type ModelConfigInput = ApiSchema<"ModelConfigIn">;
export type Credential = ApiSchema<"CredentialOut">;
export type Run = ApiSchema<"RunOut">;

export interface AgentListParams {
  q?: string;
  tag?: string;
  provider?: string;
  /** false (default, active agents) or true (archived only). */
  archived?: boolean;
  page?: number;
  page_size?: number;
}

export interface RunListParams {
  agent_id?: string;
  agent_version_id?: string;
  scenario_id?: string;
  scenario_version_id?: string;
  page?: number;
  page_size?: number;
  sort?: string;
}

export const agentsApi = {
  list: (params: AgentListParams, signal?: AbortSignal) =>
    http.get<Page<Agent>>("/agents", { query: { ...params }, signal }),
  get: (id: string, signal?: AbortSignal) => http.get<Agent>(`/agents/${id}`, { signal }),
  create: (body: AgentCreateInput) => http.post<Agent>("/agents", body),
  update: (id: string, body: AgentUpdateInput) => http.patch<Agent>(`/agents/${id}`, body),
  versions: (id: string, signal?: AbortSignal) => http.get<AgentVersionSummary[]>(`/agents/${id}/versions`, { signal }),
  createVersion: (id: string, body: AgentVersionCreateInput) => http.post<AgentVersion>(`/agents/${id}/versions`, body),
  version: (versionId: string, signal?: AbortSignal) => http.get<AgentVersion>(`/agent-versions/${versionId}`, { signal }),
  diff: (versionId: string, against: string | undefined, signal?: AbortSignal) =>
    http.get<AgentVersionDiff>(`/agent-versions/${versionId}/diff`, { query: { against }, signal }),
  test: (versionId: string, body: AgentTestInput) => http.post<AgentTestOutput>(`/agent-versions/${versionId}/test`, body),
  credentials: (signal?: AbortSignal) => http.get<Credential[]>("/credentials", { signal }),
  runs: (params: RunListParams, signal?: AbortSignal) => http.get<Page<Run>>("/runs", { query: { ...params }, signal }),
};

export function useAgents(params: AgentListParams) {
  return useQuery({
    queryKey: queryKeys.list("agents", { ...params }),
    queryFn: ({ signal }) => agentsApi.list(params, signal),
    placeholderData: keepPreviousData,
  });
}

export function useAgent(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.detail("agents", id ?? ""),
    queryFn: ({ signal }) => agentsApi.get(id!, signal),
    enabled: Boolean(id),
  });
}

export function useAgentVersions(agentId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.sub("agents", agentId ?? "", "versions"),
    queryFn: ({ signal }) => agentsApi.versions(agentId!, signal),
    enabled: Boolean(agentId),
  });
}

export function useAgentVersion(versionId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.detail("agent-versions", versionId ?? ""),
    queryFn: ({ signal }) => agentsApi.version(versionId!, signal),
    enabled: Boolean(versionId),
  });
}

/** Field-level diff of `versionId` against `against` (default: parent / previous version). */
export function useAgentVersionDiff(versionId: string | undefined, against: string | undefined) {
  return useQuery({
    queryKey: queryKeys.sub("agent-versions", versionId ?? "", "diff", { against }),
    queryFn: ({ signal }) => agentsApi.diff(versionId!, against, signal),
    enabled: Boolean(versionId) && versionId !== against,
  });
}

/** Provider credentials (admin only on the API side: pass `enabled` accordingly). */
export function useCredentials(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.list("credentials"),
    queryFn: ({ signal }) => agentsApi.credentials(signal),
    enabled,
    staleTime: 5 * 60_000,
  });
}

/** Runs filtered by agent / version / scenario (most recent first). */
export function useRunsList(params: RunListParams, enabled = true) {
  return useQuery({
    queryKey: queryKeys.list("runs", { ...params }),
    queryFn: ({ signal }) => agentsApi.runs({ sort: "-created_at", ...params }, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useCreateAgent() {
  const qc = useQueryClient();
  return useMutation<Agent, ApiError, AgentCreateInput>({
    mutationFn: agentsApi.create,
    meta: { silentError: true },
    onSuccess: () => void qc.invalidateQueries({ queryKey: queryKeys.resource("agents") }),
  });
}

export function useUpdateAgent(id: string) {
  const qc = useQueryClient();
  return useMutation<Agent, ApiError, AgentUpdateInput>({
    mutationFn: (body) => agentsApi.update(id, body),
    meta: { silentError: true },
    onSuccess: (agent) => {
      qc.setQueryData(queryKeys.detail("agents", id), agent);
      void qc.invalidateQueries({ queryKey: queryKeys.resource("agents") });
    },
  });
}

export function useCreateAgentVersion(agentId: string) {
  const qc = useQueryClient();
  return useMutation<AgentVersion, ApiError, AgentVersionCreateInput>({
    mutationFn: (body) => agentsApi.createVersion(agentId, body),
    meta: { silentError: true },
    onSuccess: (version) => {
      qc.setQueryData(queryKeys.detail("agent-versions", version.id), version);
      void qc.invalidateQueries({ queryKey: queryKeys.resource("agents") });
    },
  });
}

export function useTestAgentVersion(versionId: string) {
  return useMutation<AgentTestOutput, ApiError, AgentTestInput>({
    mutationFn: (body) => agentsApi.test(versionId, body),
    meta: { silentError: true },
  });
}
