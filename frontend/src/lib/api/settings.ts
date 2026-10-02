"use client";

/**
 * Settings API (docs/ARCHITECTURE.md §3): users (admin), service API keys (admin, full key shown
 * once), encrypted provider credentials (admin, secrets never returned), audit log (maintainer+).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "./client";
import { queryKeys } from "./query-keys";
import type { ApiSchema, Page } from "./types";

export type User = ApiSchema<"UserOut">;
export type UserCreateInput = ApiSchema<"UserCreateIn">;
export type UserUpdateInput = ApiSchema<"UserUpdateIn">;
export type ApiKey = ApiSchema<"ApiKeyOut">;
export type ApiKeyCreated = ApiSchema<"ApiKeyCreatedOut">;
export type ApiKeyCreateInput = ApiSchema<"ApiKeyCreateIn">;
export type Credential = ApiSchema<"CredentialOut">;
export type CredentialCreateInput = ApiSchema<"CredentialCreateIn">;
export type CredentialUpdateInput = ApiSchema<"CredentialUpdateIn">;
export type AuditEvent = ApiSchema<"AuditEventOut">;

export interface UserListParams {
  page?: number;
  page_size?: number;
  q?: string;
  role?: string;
  active?: boolean;
}

export interface AuditListParams {
  page?: number;
  page_size?: number;
  action?: string;
  target_type?: string;
  target_id?: string;
  actor_id?: string;
}

export const settingsApi = {
  users: (params: UserListParams = {}) => http.get<Page<User>>("/users", { query: { ...params } }),
  createUser: (body: UserCreateInput) => http.post<User>("/users", body),
  updateUser: (id: string, body: UserUpdateInput) => http.patch<User>(`/users/${id}`, body),
  apiKeys: (params: { page?: number; page_size?: number; include_revoked?: boolean } = {}) =>
    http.get<Page<ApiKey>>("/api-keys", { query: { ...params } }),
  createApiKey: (body: ApiKeyCreateInput) => http.post<ApiKeyCreated>("/api-keys", body),
  revokeApiKey: (id: string) => http.delete(`/api-keys/${id}`),
  credentials: () => http.get<Credential[]>("/credentials"),
  createCredential: (body: CredentialCreateInput) => http.post<Credential>("/credentials", body),
  updateCredential: (id: string, body: CredentialUpdateInput) => http.patch<Credential>(`/credentials/${id}`, body),
  deleteCredential: (id: string) => http.delete(`/credentials/${id}`),
  audit: (params: AuditListParams = {}) => http.get<Page<AuditEvent>>("/audit", { query: { ...params } }),
};

export function useUsers(params: UserListParams, enabled = true) {
  return useQuery({
    queryKey: queryKeys.list("users", { ...params }),
    queryFn: () => settingsApi.users(params),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: settingsApi.createUser,
    meta: { silentError: true, successMessage: "Utilisateur créé" },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("users") }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: UserUpdateInput }) => settingsApi.updateUser(id, body),
    meta: { silentError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("users") }),
  });
}

export function useApiKeys(params: { page?: number; page_size?: number; include_revoked?: boolean }) {
  return useQuery({
    queryKey: queryKeys.list("api-keys", { ...params }),
    queryFn: () => settingsApi.apiKeys(params),
    placeholderData: keepPreviousData,
  });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: settingsApi.createApiKey,
    meta: { silentError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("api-keys") }),
  });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => settingsApi.revokeApiKey(id),
    meta: { successMessage: "Clé d'API révoquée" },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("api-keys") }),
  });
}

/** Provider credentials (admin only; `enabled=false` for other roles to avoid a 403). */
export function useCredentials(enabled = true) {
  return useQuery({
    queryKey: queryKeys.list("credentials"),
    queryFn: settingsApi.credentials,
    enabled,
    retry: false,
  });
}

export function useCreateCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: settingsApi.createCredential,
    meta: { silentError: true, successMessage: "Identifiant créé" },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("credentials") }),
  });
}

export function useUpdateCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: CredentialUpdateInput }) => settingsApi.updateCredential(id, body),
    meta: { silentError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("credentials") }),
  });
}

export function useDeleteCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => settingsApi.deleteCredential(id),
    meta: { silentError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.resource("credentials") }),
  });
}

export function useAuditEvents(params: AuditListParams) {
  return useQuery({
    queryKey: queryKeys.list("audit", { ...params }),
    queryFn: () => settingsApi.audit(params),
    placeholderData: keepPreviousData,
  });
}
