/**
 * Minimal, typed fetch wrapper for the FORGE REST API (docs/ARCHITECTURE.md §12).
 *
 * - Same-origin calls to `/api/v1/...` (Next.js rewrites proxy them to FastAPI), `credentials: "include"`
 *   so the httpOnly `forge_session` cookie travels with every request.
 * - JSON and multipart bodies, query-string serialization (arrays → repeated keys).
 * - Errors are normalized to `ApiError` from the uniform body `{detail, code, errors?}`
 *   (`errors[]` = `{field, message}` on 422).
 * - 401 → redirect to `/login?next=<current path>` (opt-out with `redirectOnUnauthorized: false`).
 * - 429 → `ApiError.retryAfter` (seconds, from `Retry-After`) and a French message with the delay.
 */
import type { ApiErrorBody, ApiFieldError } from "./types";

export const API_BASE = "/api/v1";

export type QueryValue = string | number | boolean | null | undefined | ReadonlyArray<string | number>;
export type QueryParams = Record<string, QueryValue>;

export type HttpMethod = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

export interface RequestOptions {
  method?: HttpMethod;
  query?: QueryParams;
  /** JSON body (serialized with JSON.stringify). */
  json?: unknown;
  /** Multipart body. Takes precedence over `json`. */
  formData?: FormData;
  signal?: AbortSignal;
  headers?: HeadersInit;
  /** Redirect the browser to /login on 401 (default: true). */
  redirectOnUnauthorized?: boolean;
  /** How to read a successful response body (default: "json"; 204 always yields undefined). */
  responseType?: "json" | "text" | "blob";
}

/** Normalized API error. `status` is 0 for network failures. */
export class ApiError extends Error {
  readonly status: number;
  /** Stable machine-readable code (`not_found`, `conflict`, `validation_error`…). */
  readonly code: string;
  /** French, user-facing message. */
  readonly detail: string;
  /** Validation errors (422), as returned by the API. */
  readonly errors: ReadonlyArray<ApiFieldError>;
  /** `errors` indexed by field path (first message per field). */
  readonly fieldErrors: Readonly<Record<string, string>>;
  readonly body: unknown;
  /** Seconds to wait before retrying (429), when the API tells us. */
  readonly retryAfter: number | null;
  /** `X-Request-ID` of the failed response (support / logs correlation). */
  readonly requestId: string | null;

  constructor(init: {
    status: number;
    code: string;
    detail: string;
    errors?: ReadonlyArray<ApiFieldError>;
    body?: unknown;
    retryAfter?: number | null;
    requestId?: string | null;
  }) {
    super(init.detail);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.detail = init.detail;
    this.errors = init.errors ?? [];
    const fieldErrors: Record<string, string> = {};
    for (const e of this.errors) {
      if (e.field && !fieldErrors[e.field]) fieldErrors[e.field] = e.message;
    }
    this.fieldErrors = fieldErrors;
    this.body = init.body;
    this.retryAfter = init.retryAfter ?? null;
    this.requestId = init.requestId ?? null;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
  get isForbidden(): boolean {
    return this.status === 403;
  }
  get isNotFound(): boolean {
    return this.status === 404;
  }
  get isConflict(): boolean {
    return this.status === 409;
  }
  get isValidation(): boolean {
    return this.status === 422 || this.status === 400;
  }
  get isNetwork(): boolean {
    return this.status === 0;
  }
  get isServer(): boolean {
    return this.status >= 500;
  }
  get isNotImplemented(): boolean {
    return this.status === 501;
  }
  get isRateLimited(): boolean {
    return this.status === 429;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** User-facing French message for any error. */
export function errorMessage(error: unknown, fallback = "Une erreur inattendue est survenue."): string {
  if (isApiError(error)) return error.detail || fallback;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

const UNAVAILABLE = "Le service FORGE est momentanément indisponible. Réessayez dans quelques instants.";

const DEFAULT_MESSAGES: Record<number, { code: string; detail: string }> = {
  400: { code: "bad_request", detail: "Requête invalide." },
  401: { code: "unauthorized", detail: "Votre session a expiré. Veuillez vous reconnecter." },
  403: { code: "forbidden", detail: "Vous n'avez pas les droits nécessaires pour cette action." },
  404: { code: "not_found", detail: "Ressource introuvable." },
  409: { code: "conflict", detail: "Conflit avec l'état actuel de la ressource." },
  413: { code: "payload_too_large", detail: "Le contenu envoyé est trop volumineux." },
  422: { code: "validation_error", detail: "Les données envoyées sont invalides." },
  429: { code: "rate_limited", detail: "Trop de requêtes. Réessayez dans un instant." },
  501: { code: "not_implemented", detail: "Cette fonctionnalité n'est pas encore disponible." },
};

/** "30 secondes", "2 minutes", "1 h 05" — French human delay for retry messages. */
export function formatRetryDelay(seconds: number): string {
  const s = Math.max(1, Math.ceil(seconds));
  if (s < 60) return `${s} seconde${s > 1 ? "s" : ""}`;
  const minutes = Math.ceil(s / 60);
  if (minutes < 60) return `${minutes} minute${minutes > 1 ? "s" : ""}`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
}

/** Parse a `Retry-After` header (delta-seconds or HTTP date) into seconds; null when absent/unparsable. */
export function parseRetryAfter(value: string | null | undefined, now: number = Date.now()): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\d+(\.\d+)?$/.test(trimmed)) return Math.max(0, Math.ceil(Number(trimmed)));
  const date = Date.parse(trimmed);
  if (Number.isNaN(date)) return null;
  return Math.max(0, Math.ceil((date - now) / 1000));
}

function defaultFor(status: number): { code: string; detail: string } {
  const known = DEFAULT_MESSAGES[status];
  if (known) return known;
  if (status >= 500) {
    return {
      code: "server_error",
      detail: status === 502 || status === 503 || status === 504 ? UNAVAILABLE : "Erreur interne du serveur FORGE.",
    };
  }
  return { code: "http_error", detail: `Erreur HTTP ${status}.` };
}

interface FastApiValidationIssue {
  loc?: Array<string | number>;
  msg?: string;
}

function isValidationIssueArray(value: unknown): value is FastApiValidationIssue[] {
  return Array.isArray(value) && value.every((v) => typeof v === "object" && v !== null && "msg" in v);
}

function toFieldErrors(value: unknown): ApiFieldError[] {
  if (!Array.isArray(value)) return [];
  const out: ApiFieldError[] = [];
  for (const item of value) {
    if (item && typeof item === "object") {
      const rec = item as Record<string, unknown>;
      const field = typeof rec.field === "string" ? rec.field : "";
      const message = typeof rec.message === "string" ? rec.message : typeof rec.msg === "string" ? rec.msg : "";
      if (message) out.push({ field, message });
    }
  }
  return out;
}

/** Build an ApiError from a non-OK response. */
async function toApiError(response: Response): Promise<ApiError> {
  const fallback = defaultFor(response.status);
  const contentType = response.headers.get("content-type") ?? "";
  const requestId = response.headers.get("x-request-id");
  let body: unknown = undefined;
  try {
    body = contentType.includes("application/json") ? await response.json() : await response.text();
  } catch {
    body = undefined;
  }

  // Non-JSON 5xx: the proxy cannot reach the backend, or an unhandled crash upstream.
  if (response.status >= 500 && !contentType.includes("application/json")) {
    return new ApiError({ status: response.status, code: "service_unavailable", detail: UNAVAILABLE, body, requestId });
  }

  let detail = fallback.detail;
  let code = fallback.code;
  let errors: ApiFieldError[] = [];
  const retryAfter = parseRetryAfter(response.headers.get("retry-after"));

  if (body && typeof body === "object") {
    const record = body as Partial<ApiErrorBody> & { detail?: unknown; errors?: unknown };
    if (typeof record.code === "string" && record.code) code = record.code;
    if (typeof record.detail === "string" && record.detail.trim()) {
      detail = record.detail;
    } else if (isValidationIssueArray(record.detail)) {
      // Raw FastAPI validation body (should not happen with forge.api.errors, kept for robustness).
      errors = record.detail.map((issue) => ({
        field: (issue.loc ?? [])
          .filter((p) => p !== "body" && p !== "query" && p !== "path")
          .map(String)
          .join("."),
        message: issue.msg ?? "",
      }));
    }
    const listed = toFieldErrors(record.errors);
    if (listed.length) errors = listed;
  }

  if (response.status === 429 && retryAfter !== null && retryAfter > 0 && detail === fallback.detail) {
    detail = `Trop de requêtes. Réessayez dans ${formatRetryDelay(retryAfter)}.`;
  }

  return new ApiError({ status: response.status, code, detail, errors, body, retryAfter, requestId });
}

/** Serialize query params (arrays → repeated keys; null/undefined/"" skipped). */
export function buildQuery(query?: QueryParams): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const v of value) params.append(key, String(v));
    } else {
      params.append(key, String(value));
    }
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

/** Absolute-path URL for an API path (useful for <a href> downloads). */
export function apiUrl(path: string, query?: QueryParams): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${normalized}${buildQuery(query)}`;
}

let redirecting = false;

/** Send the browser to /login, preserving the current location in `?next=`. */
export function redirectToLogin(): void {
  if (typeof window === "undefined" || redirecting) return;
  const { pathname, search } = window.location;
  if (pathname.startsWith("/login")) return;
  redirecting = true;
  const next = `${pathname}${search}`;
  const target = next && next !== "/" ? `/login?next=${encodeURIComponent(next)}` : "/login";
  window.location.assign(target);
}

/** Core request function. */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const {
    method = "GET",
    query,
    json,
    formData,
    signal,
    headers,
    redirectOnUnauthorized = true,
    responseType = "json",
  } = options;

  const finalHeaders = new Headers(headers);
  finalHeaders.set("Accept", responseType === "json" ? "application/json" : "*/*");

  let body: BodyInit | undefined;
  if (formData) {
    body = formData; // the browser sets the multipart boundary
  } else if (json !== undefined) {
    finalHeaders.set("Content-Type", "application/json");
    body = JSON.stringify(json);
  }

  let response: Response;
  try {
    response = await fetch(apiUrl(path, query), {
      method,
      headers: finalHeaders,
      body,
      signal,
      credentials: "include",
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError({
      status: 0,
      code: "network_error",
      detail: "Impossible de joindre le serveur FORGE. Vérifiez votre connexion.",
      body: error,
    });
  }

  if (!response.ok) {
    const apiError = await toApiError(response);
    if (apiError.status === 401 && redirectOnUnauthorized) redirectToLogin();
    throw apiError;
  }

  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return undefined as T;
  }

  switch (responseType) {
    case "text":
      return (await response.text()) as T;
    case "blob":
      return (await response.blob()) as T;
    default: {
      const text = await response.text();
      if (!text) return undefined as T;
      try {
        return JSON.parse(text) as T;
      } catch {
        throw new ApiError({
          status: response.status,
          code: "invalid_response",
          detail: "Réponse du serveur illisible.",
          body: text,
        });
      }
    }
  }
}

/** Convenience verbs. */
export const http = {
  get: <T>(path: string, options?: Omit<RequestOptions, "method" | "json" | "formData">) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, json?: unknown, options?: Omit<RequestOptions, "method" | "json">) =>
    request<T>(path, { ...options, method: "POST", json }),
  put: <T>(path: string, json?: unknown, options?: Omit<RequestOptions, "method" | "json">) =>
    request<T>(path, { ...options, method: "PUT", json }),
  patch: <T>(path: string, json?: unknown, options?: Omit<RequestOptions, "method" | "json">) =>
    request<T>(path, { ...options, method: "PATCH", json }),
  delete: <T = void>(path: string, options?: Omit<RequestOptions, "method">) =>
    request<T>(path, { ...options, method: "DELETE" }),
  upload: <T>(path: string, formData: FormData, options?: Omit<RequestOptions, "method" | "formData" | "json">) =>
    request<T>(path, { ...options, method: "POST", formData }),
};

/** Trigger a browser download for a Blob. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
