import { Suspense } from "react";
import type { Metadata } from "next";

import { VersionDetailView } from "@/components/agents/version-detail-view";

export const metadata: Metadata = { title: "Version d'agent" };

export default async function AgentVersionPage({ params }: { params: Promise<{ id: string; versionId: string }> }) {
  const { id, versionId } = await params;
  return (
    <Suspense>
      <VersionDetailView agentId={id} versionId={versionId} />
    </Suspense>
  );
}
