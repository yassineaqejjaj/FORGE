import type { Metadata } from "next";
import { Play } from "lucide-react";

import { ModulePlaceholder } from "@/components/layout/module-placeholder";

export const metadata: Metadata = { title: "Runs" };

export default function Page() {
  return (
    <ModulePlaceholder
      eyebrow="Laboratoire"
      title="Runs"
      icon={<Play />}
      description="Chaque exécution d'un agent sur un scénario : trace, sortie, scores, erreurs et feedback."
      upcoming={[
        "Liste filtrable des runs (statut, agent, scénario, origine)",
        "Détail en 3 colonnes : scénario | trace | composite et dimensions",
        "Provenance de chaque score jusqu'aux preuves",
        "Ré-évaluation, annulation, nouvel essai",
      ]}
    />
  );
}
