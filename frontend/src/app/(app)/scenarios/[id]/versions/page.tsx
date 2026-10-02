import { redirect } from "next/navigation";

/** `/scenarios/{id}/versions` → the Versions tab of the scenario page. */
export default async function ScenarioVersionsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/scenarios/${id}?tab=versions`);
}
