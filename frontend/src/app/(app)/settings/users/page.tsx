import type { Metadata } from "next";
import { Suspense } from "react";

import { RoleGate } from "@/components/auth/require-role";
import { UsersAdmin } from "@/components/settings/users-admin";

export const metadata: Metadata = { title: "Utilisateurs · Paramètres" };

export default function Page() {
  return (
    <RoleGate min="admin">
      <Suspense>
        <UsersAdmin />
      </Suspense>
    </RoleGate>
  );
}
