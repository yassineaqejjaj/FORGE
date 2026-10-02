import type { Metadata } from "next";

import { RoleGate } from "@/components/auth/require-role";
import { ConfigEditor } from "@/components/evaluation-configs/config-editor";

export const metadata: Metadata = { title: "Nouvelle version de configuration" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <RoleGate min="maintainer">
      <ConfigEditor configId={id} />
    </RoleGate>
  );
}
