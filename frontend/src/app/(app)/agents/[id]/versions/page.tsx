import { redirect } from "next/navigation";

/** `/agents/{id}/versions` has no page of its own: the timeline lives on the agent page. */
export default async function AgentVersionsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/agents/${id}`);
}
