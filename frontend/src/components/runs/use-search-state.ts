"use client";

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

export type SearchPatchValue = string | number | boolean | ReadonlyArray<string> | null | undefined;
export type SearchPatch = Record<string, SearchPatchValue>;

export interface SearchState {
  params: URLSearchParams;
  get: (key: string) => string | undefined;
  getAll: (key: string) => string[];
  getNumber: (key: string) => number | undefined;
  getBool: (key: string) => boolean | undefined;
  /** Merge `patch` into the URL (null/undefined/""/[] remove the key). Resets `page` unless it is patched. */
  set: (patch: SearchPatch, options?: { resetPage?: boolean; push?: boolean }) => void;
  /** Remove every key except `keep`. */
  clear: (keep?: string[]) => void;
  /** Number of active keys among `keys`. */
  countActive: (keys: readonly string[]) => number;
}

/** URL-synced UI state (filters, pagination, selected tabs) for the App Router. */
export function useSearchState(): SearchState {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const raw = searchParams.toString();

  const params = React.useMemo(() => new URLSearchParams(raw), [raw]);

  const navigate = React.useCallback(
    (next: URLSearchParams, push = false) => {
      const qs = next.toString();
      const url = qs ? `${pathname}?${qs}` : pathname;
      if (push) router.push(url, { scroll: false });
      else router.replace(url, { scroll: false });
    },
    [pathname, router],
  );

  const set = React.useCallback<SearchState["set"]>(
    (patch, { resetPage = true, push = false } = {}) => {
      const next = new URLSearchParams(raw);
      for (const [key, value] of Object.entries(patch)) {
        next.delete(key);
        if (value === null || value === undefined || value === "") continue;
        if (Array.isArray(value)) {
          for (const v of value as ReadonlyArray<string>) if (v) next.append(key, v);
        } else {
          next.set(key, String(value));
        }
      }
      if (resetPage && !("page" in patch)) next.delete("page");
      navigate(next, push);
    },
    [navigate, raw],
  );

  const clear = React.useCallback<SearchState["clear"]>(
    (keep = []) => {
      const next = new URLSearchParams();
      const current = new URLSearchParams(raw);
      for (const key of keep) for (const v of current.getAll(key)) next.append(key, v);
      navigate(next);
    },
    [navigate, raw],
  );

  return React.useMemo<SearchState>(
    () => ({
      params,
      get: (key) => params.get(key) || undefined,
      getAll: (key) => params.getAll(key).filter(Boolean),
      getNumber: (key) => {
        const v = params.get(key);
        if (v === null || v === "") return undefined;
        const n = Number(v);
        return Number.isFinite(n) ? n : undefined;
      },
      getBool: (key) => {
        const v = params.get(key);
        if (v === "true" || v === "1") return true;
        if (v === "false" || v === "0") return false;
        return undefined;
      },
      set,
      clear,
      countActive: (keys) => keys.filter((k) => params.getAll(k).some(Boolean)).length,
    }),
    [params, set, clear],
  );
}

/** "2026-10-01" (date input) → ISO start/end of day in local time. */
export function dateInputToIso(value: string | undefined, endOfDay = false): string | undefined {
  if (!value) return undefined;
  const d = new Date(`${value}T${endOfDay ? "23:59:59.999" : "00:00:00"}`);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}
