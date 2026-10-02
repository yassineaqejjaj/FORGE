import { Suspense } from "react";
import type { Metadata } from "next";

import { NewScenarioVersionView } from "@/components/scenarios/scenario-editor-pages";

export const metadata: Metadata = { title: "Nouvelle version de scénario" };

export default async function NewScenarioVersionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <NewScenarioVersionView scenarioId={id} />
    </Suspense>
  );
}
