import type { Metadata } from "next";
import { Suspense } from "react";

import { RoleGate } from "@/components/auth/require-role";
import { AuditLog } from "@/components/settings/audit-log";

export const metadata: Metadata = { title: "Audit · Paramètres" };

export default function Page() {
  return (
    <RoleGate min="maintainer">
      <Suspense>
        <AuditLog />
      </Suspense>
    </RoleGate>
  );
}
