import type { Metadata } from "next";

import { NewScenarioView } from "@/components/scenarios/scenario-editor-pages";

export const metadata: Metadata = { title: "Nouveau scénario" };

export default function NewScenarioPage() {
  return <NewScenarioView />;
}
