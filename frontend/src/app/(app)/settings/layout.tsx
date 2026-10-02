"use client";

import * as React from "react";
import { Settings } from "lucide-react";

import { RoleGate } from "@/components/auth/require-role";
import { LocalTabs } from "@/components/layout/local-tabs";
import { SETTINGS_NAV } from "@/components/layout/nav";
import { PageHeader } from "@/components/ui/page-header";
import { useCurrentUser } from "@/hooks/use-current-user";

/** Settings shell: tabs filtered by role (users / API keys / credentials: admin · audit: maintainer). */
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { hasRole } = useCurrentUser();
  const tabs = SETTINGS_NAV.filter((t) => !t.minRole || hasRole(t.minRole));

  return (
    <RoleGate min="maintainer">
      <PageHeader
        eyebrow="Configuration"
        title="Paramètres"
        icon={<Settings />}
        description="Utilisateurs, clés d'API, identifiants fournisseurs et journal d'audit de la plateforme."
      >
        <LocalTabs label="Sections des paramètres" tabs={tabs.map((t) => ({ href: t.href, label: t.label, icon: t.icon }))} />
      </PageHeader>
      {children}
    </RoleGate>
  );
}
