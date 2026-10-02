"use client";

import * as React from "react";
import Link from "next/link";

import { Button, type ButtonProps } from "@/components/ui/button";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useCurrentUser } from "@/hooks/use-current-user";
import { ROLE_META, type Role } from "@/lib/enums";

export interface RoleButtonProps extends ButtonProps {
  /** Minimum platform role for the action (UI hint only, the API enforces it). */
  minRole: Role;
  /** Renders a Next link when allowed. */
  href?: string;
  /** Another reason to disable the action (shown in the tooltip). */
  disabledReason?: string | null;
}

/** "Réservé au rôle Éditeur ou supérieur." */
export function roleRequirement(min: Role): string {
  return `Réservé au rôle ${ROLE_META[min].label.toLowerCase()} ou supérieur.`;
}

/**
 * Action button that stays visible but disabled (with an explanatory tooltip) when the current
 * user's role is below `minRole`, or when `disabledReason` is set.
 */
export function RoleButton({ minRole, href, disabledReason, children, disabled, ...props }: RoleButtonProps) {
  const { hasRole } = useCurrentUser();
  const allowed = hasRole(minRole);
  const reason = !allowed ? roleRequirement(minRole) : disabledReason || null;

  if (reason) {
    return (
      <SimpleTooltip content={reason}>
        <span tabIndex={0} className="inline-flex rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <Button {...props} disabled aria-disabled>
            {children}
          </Button>
        </span>
      </SimpleTooltip>
    );
  }
  if (href && !disabled) {
    const { leftIcon, rightIcon, loading: _loading, ...rest } = props;
    return (
      <Button asChild {...rest}>
        <Link href={href}>
          {leftIcon}
          {children}
          {rightIcon}
        </Link>
      </Button>
    );
  }
  return (
    <Button {...props} disabled={disabled}>
      {children}
    </Button>
  );
}
