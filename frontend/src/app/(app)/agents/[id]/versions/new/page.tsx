import { Suspense } from "react";
import type { Metadata } from "next";

import { NewVersionView } from "@/components/agents/version-form";

export const metadata: Metadata = { title: "Nouvelle version d'agent" };

export default async function NewAgentVersionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <NewVersionView agentId={id} />
    </Suspense>
  );
}
