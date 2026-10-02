import type { Metadata } from "next";

import { RoleGate } from "@/components/auth/require-role";
import { JudgeForm } from "@/components/judges/judge-form";

export const metadata: Metadata = { title: "Nouvelle version de juge" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <RoleGate min="maintainer">
      <JudgeForm judgeId={id} />
    </RoleGate>
  );
}
