"use client";

import * as React from "react";
import { Lock } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { useCurrentUser } from "@/hooks/use-current-user";
import type { Role } from "@/lib/enums";

export interface RequireRoleProps {
  /** Minimum platform role required to render `children`. */
  min: Role;
  /** Rendered when the user lacks the role (default: nothing). */
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Hides UI the user is not allowed to use: <RequireRole min="editor"><Button>Lancer</Button></RequireRole>.
 * UI-only convenience — the API enforces permissions server-side.
 */
export function RequireRole({ min, fallback = null, children }: RequireRoleProps) {
  const { hasRole } = useCurrentUser();
  return <>{hasRole(min) ? children : fallback}</>;
}

export interface RoleGateProps {
  /** Minimum platform role required to see the page. */
  min: Role;
  children: React.ReactNode;
}

const ROLE_LABELS: Record<Role, string> = {
  viewer: "lecteur",
  evaluator: "évaluateur",
  editor: "éditeur",
  maintainer: "mainteneur",
  admin: "administrateur",
};

/** Page-level variant: renders an "access restricted" state instead of the page body. */
export function RoleGate({ min, children }: RoleGateProps) {
  const { hasRole, isLoading } = useCurrentUser();
  if (isLoading) return null;
  if (hasRole(min)) return <>{children}</>;
  return (
    <EmptyState
      size="lg"
      icon={<Lock />}
      title="Accès réservé"
      description={`Cette page nécessite le rôle ${ROLE_LABELS[min]} ou supérieur. Contactez un administrateur FORGE si vous pensez devoir y accéder.`}
    />
  );
}
