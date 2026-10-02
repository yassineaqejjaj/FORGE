/**
 * Query-key factory. Every key starts with `["forge", <resource>]`, so
 * `invalidateQueries({ queryKey: queryKeys.resource("runs") })` refreshes every runs query
 * (lists, details, sub-resources).
 *
 *   useQuery({ queryKey: queryKeys.list("runs", { page, status }), … })
 *   useQuery({ queryKey: queryKeys.detail("runs", id), … })
 *   useQuery({ queryKey: queryKeys.sub("runs", id, "scores"), … })
 */
import type { QueryParams } from "./client";

const ROOT = "forge" as const;

/** API resources (first path segment under /api/v1). */
export type ResourceName =
  | "agents"
  | "agent-versions"
  | "prompts"
  | "model-configurations"
  | "tool-configurations"
  | "scenarios"
  | "scenario-versions"
  | "datasets"
  | "criteria"
  | "error-types"
  | "runs"
  | "reviews"
  | "judges"
  | "evaluation-configs"
  | "benchmarks"
  | "benchmark-executions"
  | "experiments"
  | "calibration"
  | "dashboard"
  | "errors"
  | "results"
  | "feedback-reports"
  | "users"
  | "api-keys"
  | "credentials"
  | "audit";

/** Drop empty values so `{status: undefined}` and `{}` share a cache entry. */
function cleanParams(params?: QueryParams): QueryParams {
  if (!params) return {};
  const out: QueryParams = {};
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v) && v.length === 0) continue;
    out[k] = v;
  }
  return out;
}

export const queryKeys = {
  all: [ROOT] as const,
  me: () => [ROOT, "auth", "me"] as const,
  meta: () => [ROOT, "meta"] as const,

  /** Every query of a resource. */
  resource: (name: ResourceName) => [ROOT, name] as const,
  /** Paginated / filtered list. */
  list: (name: ResourceName, params?: QueryParams) => [ROOT, name, "list", cleanParams(params)] as const,
  /** Single entity. */
  detail: (name: ResourceName, id: string) => [ROOT, name, "detail", id] as const,
  /** Sub-resource of an entity (`/runs/{id}/scores` → sub("runs", id, "scores")). */
  sub: (name: ResourceName, id: string, child: string, params?: QueryParams) =>
    [ROOT, name, "detail", id, child, cleanParams(params)] as const,
};
