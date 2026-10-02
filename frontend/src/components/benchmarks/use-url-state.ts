"use client";

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/**
 * URL-synced state for list filters, tabs and selections (`?group_by=agent&page=2`).
 * Values are strings; an empty string / null removes the parameter. Updates use `router.replace`
 * (no history entry per keystroke) and keep the scroll position.
 */
export function useUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const get = React.useCallback((key: string): string | null => searchParams.get(key), [searchParams]);

  const set = React.useCallback(
    (updates: Record<string, string | number | boolean | null | undefined>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(updates)) {
        if (value === null || value === undefined || value === "" || value === false) params.delete(key);
        else params.set(key, String(value));
      }
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  return { get, set, searchParams };
}

/** Page number from the URL (1-based, defaults to 1). */
export function pageFrom(value: string | null): number {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 ? n : 1;
}

/** Debounced text input bound to a URL parameter. */
export function useUrlSearch(key = "q", delay = 300) {
  const { get, set } = useUrlState();
  const urlValue = get(key) ?? "";
  const [value, setValue] = React.useState(urlValue);
  const lastPushed = React.useRef(urlValue);

  React.useEffect(() => {
    if (urlValue !== lastPushed.current) {
      lastPushed.current = urlValue;
      setValue(urlValue);
    }
  }, [urlValue]);

  React.useEffect(() => {
    if (value === lastPushed.current) return;
    const t = window.setTimeout(() => {
      lastPushed.current = value;
      set({ [key]: value.trim() || null, page: null });
    }, delay);
    return () => window.clearTimeout(t);
  }, [value, delay, key, set]);

  return { value, setValue, applied: urlValue };
}
