"use client";

import Link from "next/link";
import { LogOut, Settings } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { RoleBadge } from "@/components/domain/enum-badge";
import { UserAvatar } from "@/components/domain/user-avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useLogout } from "@/lib/api/auth";

/** Header user menu: identity, role, clearance, settings, logout. */
export function UserMenu() {
  const { user, hasRole } = useCurrentUser();
  const logout = useLogout();
  if (!user) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex items-center rounded-full p-0.5 transition-shadow hover:ring-2 hover:ring-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`Menu utilisateur — ${user.full_name || user.email}`}
        >
          <UserAvatar user={user} size="md" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <div className="flex items-start gap-3 px-2 py-2.5">
          <UserAvatar user={user} size="lg" />
          <div className="grid min-w-0 gap-1">
            <p className="truncate text-sm font-semibold leading-tight">{user.full_name || user.email}</p>
            <p className="truncate text-xs text-muted-foreground">{user.email}</p>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <RoleBadge value={user.role} withTooltip={false} />
              <ClassificationBadge level={user.clearance} prefix="Habilitation" showLabel={false} noTooltip />
            </div>
          </div>
        </div>
        <DropdownMenuSeparator />
        {hasRole("maintainer") ? (
          <>
            <DropdownMenuItem asChild>
              <Link href="/settings">
                <Settings aria-hidden />
                Paramètres
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
          </>
        ) : null}
        <DropdownMenuItem destructive onSelect={() => logout.mutate()} disabled={logout.isPending}>
          <LogOut aria-hidden />
          Se déconnecter
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
