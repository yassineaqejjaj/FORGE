import type { Metadata } from "next";
import { Suspense } from "react";

import { RoleGate } from "@/components/auth/require-role";
import { CredentialsAdmin } from "@/components/settings/credentials-admin";

export const metadata: Metadata = { title: "Identifiants · Paramètres" };

export default function Page() {
  return (
    <RoleGate min="admin">
      <Suspense>
        <CredentialsAdmin />
      </Suspense>
    </RoleGate>
  );
}
