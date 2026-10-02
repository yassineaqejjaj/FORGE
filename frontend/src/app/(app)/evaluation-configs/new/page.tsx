import type { Metadata } from "next";

import { RoleGate } from "@/components/auth/require-role";
import { ConfigEditor } from "@/components/evaluation-configs/config-editor";

export const metadata: Metadata = { title: "Nouvelle configuration de score" };

export default function Page() {
  return (
    <RoleGate min="maintainer">
      <ConfigEditor />
    </RoleGate>
  );
}
