"use client";

import { useQuery } from "@tanstack/react-query";

import type { NavBadgeKey } from "@/components/layout/nav";
import { useCurrentUser } from "@/hooks/use-current-user";
import { http } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type { Page } from "@/lib/api/types";

const REFRESH_MS = 60_000;
/** Failed executions of the last 24 h ask for attention; older ones are history. */
const FAILED_WINDOW_MS = 24 * 60 * 60 * 1000;

export interface NavBadge {
  count: number;
  /** Accessible sentence (« 3 exécutions en échec depuis 24 h »). */
  label: string;
  tone: "red" | "brand";
}

function useTotal(key: readonly unknown[], path: string, query: Record<string, string | number>, enabled: boolean) {
  return useQuery<Page<unknown>, Error, number>({
    queryKey: key,
    queryFn: ({ signal }) => http.get<Page<unknown>>(path, { query, signal }),
    select: (page) => page.total,
    enabled,
    staleTime: REFRESH_MS,
    refetchInterval: REFRESH_MS,
    refetchIntervalInBackground: false,
    retry: false,
    meta: { toastError: false },
  });
}

/**
 * Attention counters of the navigation. A badge exists only when it carries information:
 * failed executions of the last 24 h, and the priority review queue of the current evaluator
 * (judges disagree, low confidence or gold runs) — not every run never reviewed by a human.
 */
export function useNavBadges(): Partial<Record<NavBadgeKey, NavBadge>> {
  const { hasRole, user } = useCurrentUser();
  // Rounded to the hour so the query key (and the cache) stays stable between renders.
  const since = new Date(Math.floor((Date.now() - FAILED_WINDOW_MS) / 3_600_000) * 3_600_000).toISOString();

  const failed = useTotal(
    [...queryKeys.list("runs", { status: "failed", created_from: since, page_size: 1 }), "nav-badge"],
    "/runs",
    { status: "failed", created_from: since, page_size: 1 },
    Boolean(user),
  );
  const reviews = useTotal(
    [...queryKeys.list("reviews", { page_size: 1, priority: true }), "nav-badge"],
    "/reviews/queue",
    { page_size: 1, priority: "true" },
    Boolean(user) && hasRole("evaluator"),
  );

  const badges: Partial<Record<NavBadgeKey, NavBadge>> = {};
  if (failed.data && failed.data > 0) {
    badges.failedRuns = {
      count: failed.data,
      label: `${failed.data} exécution${failed.data > 1 ? "s" : ""} en échec depuis 24 h`,
      tone: "red",
    };
  }
  if (reviews.data && reviews.data > 0) {
    badges.reviewQueue = {
      count: reviews.data,
      label: `${reviews.data} revue${reviews.data > 1 ? "s" : ""} prioritaire${reviews.data > 1 ? "s" : ""} en attente`,
      tone: "brand",
    };
  }
  return badges;
}

export function formatBadgeCount(count: number): string {
  return count > 99 ? "99+" : String(count);
}
