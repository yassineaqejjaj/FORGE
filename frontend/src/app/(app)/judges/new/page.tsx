import type { Metadata } from "next";

import { RoleGate } from "@/components/auth/require-role";
import { JudgeForm } from "@/components/judges/judge-form";

export const metadata: Metadata = { title: "Nouveau juge" };

export default function Page() {
  return (
    <RoleGate min="maintainer">
      <JudgeForm />
    </RoleGate>
  );
}
