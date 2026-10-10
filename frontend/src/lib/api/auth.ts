"use client";

/**
 * Session hooks: `GET /auth/me` bootstrap, login, logout.
 * The backend owns the session (httpOnly `forge_session` cookie); the UI never stores tokens.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";

import { http, isApiError, type ApiError } from "./client";
import { queryKeys } from "./query-keys";
import type { CurrentUser, LoginRequest, LoginResponse } from "./types";

export const authApi = {
  me: (options?: { redirectOnUnauthorized?: boolean; signal?: AbortSignal }) =>
    http.get<CurrentUser>("/auth/me", options),
  login: async (body: LoginRequest): Promise<CurrentUser> => {
    const res = await http.post<LoginResponse | CurrentUser>("/auth/login", body, { redirectOnUnauthorized: false });
    // `LoginOut` = {user, token}; tolerate a bare user body as well.
    return "user" in res && res.user ? res.user : (res as CurrentUser);
  },
  logout: () => http.post<void>("/auth/logout", undefined, { redirectOnUnauthorized: false }),
  completeOnboarding: () => http.post<CurrentUser>("/auth/onboarding/complete"),
};

export interface UseMeOptions extends Omit<UseQueryOptions<CurrentUser, ApiError>, "queryKey" | "queryFn"> {
  /** Redirect to /login on 401 (default: true). The login page passes false. */
  redirectOnUnauthorized?: boolean;
}

/** Current session user (`GET /auth/me`). */
export function useMe({ redirectOnUnauthorized = true, ...options }: UseMeOptions = {}) {
  return useQuery<CurrentUser, ApiError>({
    queryKey: queryKeys.me(),
    queryFn: ({ signal }) => authApi.me({ redirectOnUnauthorized, signal }),
    staleTime: 5 * 60_000,
    retry: (count, error) => !(isApiError(error) && (error.isUnauthorized || error.isForbidden)) && count < 1,
    ...options,
  });
}

/** `POST /auth/login` — on success the returned user seeds the `me` cache. */
export function useLogin() {
  const qc = useQueryClient();
  return useMutation<CurrentUser, ApiError, LoginRequest>({
    mutationFn: authApi.login,
    meta: { silentError: true },
    onSuccess: (user) => {
      qc.clear();
      qc.setQueryData(queryKeys.me(), user);
    },
  });
}

/** `POST /auth/logout`, then clear every cached query and go to /login (even if the call fails). */
export function useLogout() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: () => authApi.logout(),
    meta: { silentError: true },
    onSettled: () => {
      qc.clear();
      if (typeof window !== "undefined") window.location.assign("/login");
    },
  });
}

/** `POST /auth/onboarding/complete` — idempotent; the returned user refreshes the `me` cache. */
export function useCompleteOnboarding() {
  const qc = useQueryClient();
  return useMutation<CurrentUser, ApiError, void>({
    mutationFn: authApi.completeOnboarding,
    meta: { silentError: true },
    onSuccess: (user) => qc.setQueryData(queryKeys.me(), user),
  });
}
