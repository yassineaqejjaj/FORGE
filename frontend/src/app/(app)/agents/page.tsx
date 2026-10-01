import type { Metadata } from "next";
import { Bot } from "lucide-react";

import { ModulePlaceholder } from "@/components/layout/module-placeholder";

export const metadata: Metadata = { title: "Agents" };

export default function Page() {
  return (
    <ModulePlaceholder
      eyebrow="Laboratoire"
      title="Agents"
      icon={<Bot />}
      description="Agents évalués et leurs versions immuables : prompt, modèle, outils, contexte, budget."
      upcoming={[
        "Liste des agents et de leurs versions (hash de contenu)",
        "Diff entre deux versions",
        "Test rapide d'une version",
        "Prompts, configurations de modèles et d'outils",
      ]}
    />
  );
}
