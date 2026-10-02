import type { Metadata } from "next";

import { AgentDetailView } from "@/components/agents/agent-detail-view";

export const metadata: Metadata = { title: "Agent" };

export default async function AgentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AgentDetailView agentId={id} />;
}
