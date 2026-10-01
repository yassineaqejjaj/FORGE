"use client";

import * as React from "react";

import { useMe } from "@/lib/api/auth";
import type { CurrentUser } from "@/lib/api/types";
import { hasMinRole, toClassification, type Classification, type Role } from "@/lib/enums";

export interface CurrentUserState {
  /** Authenticated user (undefined while loading or signed out). */
  user: CurrentUser | undefined;
  role: Role | null;
  clearance: Classification;
  isLoading: boolean;
  /** True when the user's platform role is at least `min` (viewer < evaluator < editor < maintainer < admin). */
  hasRole: (min: Role) => boolean;
  /** True when the user's clearance covers classification `level`. */
  canSee: (level: number | null | undefined) => boolean;
}

/**
 * Current session user and role helpers. UI-only convenience: the API enforces every permission
 * server-side (a hidden button is never a security boundary).
 */
export function useCurrentUser(): CurrentUserState {
  const me = useMe();
  const user = me.data;
  const role = user?.role ?? null;
  const clearance = toClassification(user?.clearance);
  const hasRole = React.useCallback((min: Role) => hasMinRole(role, min), [role]);
  const canSee = React.useCallback((level: number | null | undefined) => toClassification(level) <= clearance, [clearance]);
  return { user, role, clearance, isLoading: me.isPending, hasRole, canSee };
}

/** `const canEdit = useHasRole("editor")`. */
export function useHasRole(min: Role): boolean {
  return useCurrentUser().hasRole(min);
}
