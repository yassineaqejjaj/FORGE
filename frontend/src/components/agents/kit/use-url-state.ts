"use client";

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

export type UrlStateValue = string | number | boolean | null | undefined;

/**
 * URL-synced page state (filters, pagination, tabs). Values are read from the query string and
 * written with `router.replace` (no history spam, no scroll jump). Changing any key other than
 * `page` resets the pagination.
 */
export function useUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const get = React.useCallback((key: string): string => searchParams.get(key) ?? "", [searchParams]);

  const set = React.useCallback(
    (updates: Record<string, UrlStateValue>, options: { resetPage?: boolean } = {}) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(updates)) {
        if (value === null || value === undefined || value === "" || value === false) next.delete(key);
        else next.set(key, String(value));
      }
      if ((options.resetPage ?? true) && !("page" in updates)) next.delete("page");
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const page = Math.max(1, Number.parseInt(searchParams.get("page") ?? "1", 10) || 1);

  return { searchParams, get, set, page };
}
