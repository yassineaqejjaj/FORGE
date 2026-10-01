import type { Metadata } from "next";
import { SlidersHorizontal } from "lucide-react";

import { ModulePlaceholder } from "@/components/layout/module-placeholder";

export const metadata: Metadata = { title: "Configurations d'évaluation" };

export default function Page() {
  return (
    <ModulePlaceholder
      eyebrow="Évaluer"
      title="Configurations d'évaluation"
      icon={<SlidersHorizontal />}
      description="Pondérations des dimensions, garde-fous, juges épinglés et méthode d'agrégation."
      upcoming={[
        "Pondérations par dimension et par critère",
        "Garde-fous (invalider / plafonner)",
        "Agrégation multi-juges",
        "Aperçu de l'effet d'une configuration sur des runs existants",
      ]}
    />
  );
}
