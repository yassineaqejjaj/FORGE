/**
 * Shell-level API types only (errors, pagination, session). Feature payloads come from the
 * generated OpenAPI schema (`npm run gen:api` → `schema.d.ts`): use `ApiSchema<"RunRead">`.
 */
import type { Role } from "@/lib/enums";
import type { components } from "./schema";

/** One validation issue of a 422 body (`forge.api.errors.format_validation_errors`). */
export interface ApiFieldError {
  /** Dotted field path ("agent.budget.max_tokens"), or "requête". */
  field: string;
  message: string;
}

/** Uniform error body `{detail, code, errors?}` (docs/ARCHITECTURE.md §12). */
export interface ApiErrorBody {
  detail: string;
  code: string;
  errors?: ApiFieldError[];
}

/** Paginated list `Page[T]` (`?page=1&page_size=25`). */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface PageParams {
  page?: number;
  page_size?: number;
}

export const DEFAULT_PAGE_SIZE = 25;
export const MAX_PAGE_SIZE = 200;

/** Authenticated user (`UserOut`) returned by `GET /auth/me` and inside `POST /auth/login`. */
export interface CurrentUser {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  /** Classification clearance 0..3 (C0 → C3). */
  clearance: number;
  avatar_color: string | null;
  active?: boolean;
  last_login_at?: string | null;
  created_at?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
  /** « Rester connecté » — false: browser-session cookie. */
  remember?: boolean;
}

/** `POST /auth/login` response (`LoginOut`): the session itself travels in the httpOnly cookie. */
export interface LoginResponse {
  user: CurrentUser;
  /** Only returned when explicitly requested (CLI); the UI ignores it. */
  token?: string | null;
}

/** Schema lookup helper over the generated OpenAPI components: `ApiSchema<"RunRead">`. */
export type ApiSchema<Name extends keyof components["schemas"]> = components["schemas"][Name];
