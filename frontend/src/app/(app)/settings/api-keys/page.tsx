import type { Metadata } from "next";
import { Suspense } from "react";

import { RoleGate } from "@/components/auth/require-role";
import { ApiKeysAdmin } from "@/components/settings/api-keys-admin";

export const metadata: Metadata = { title: "Clés d'API · Paramètres" };

export default function Page() {
  return (
    <RoleGate min="admin">
      <Suspense>
        <ApiKeysAdmin />
      </Suspense>
    </RoleGate>
  );
}
