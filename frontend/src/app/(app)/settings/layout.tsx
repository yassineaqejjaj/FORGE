"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Settings } from "lucide-react";

import { RoleGate } from "@/components/auth/require-role";
import { isActiveHref, SETTINGS_NAV } from "@/components/layout/nav";
import { PageHeader } from "@/components/ui/page-header";
import { useCurrentUser } from "@/hooks/use-current-user";
import { cn } from "@/lib/utils";

/** Settings shell: tabs filtered by role (users / API keys / credentials: admin · audit: maintainer). */
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { hasRole } = useCurrentUser();
  const tabs = SETTINGS_NAV.filter((t) => !t.minRole || hasRole(t.minRole));

  return (
    <RoleGate min="maintainer">
      <PageHeader
        eyebrow="Administration"
        title="Paramètres"
        icon={<Settings />}
        description="Utilisateurs, clés d'API, identifiants fournisseurs et journal d'audit de la plateforme."
      >
        <nav aria-label="Sections des paramètres" className="-mb-px overflow-x-auto border-b border-border [scrollbar-width:none]">
          <ul className="flex min-w-max gap-1">
            {tabs.map((tab) => {
              const active = isActiveHref(pathname, tab.href);
              const Icon = tab.icon;
              return (
                <li key={tab.href}>
                  <Link
                    href={tab.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "inline-flex h-9 items-center gap-2 border-b-2 px-3 text-[13px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      active
                        ? "border-brand text-foreground"
                        : "border-transparent text-muted-foreground hover:border-border-strong hover:text-foreground",
                    )}
                  >
                    <Icon className="size-4" aria-hidden />
                    {tab.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </PageHeader>
      {children}
    </RoleGate>
  );
}
