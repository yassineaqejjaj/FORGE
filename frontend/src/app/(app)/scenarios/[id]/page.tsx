import { Suspense } from "react";
import type { Metadata } from "next";

import { ScenarioDetailView } from "@/components/scenarios/scenario-detail-view";

export const metadata: Metadata = { title: "Scénario" };

export default async function ScenarioPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <ScenarioDetailView scenarioId={id} />
    </Suspense>
  );
}
