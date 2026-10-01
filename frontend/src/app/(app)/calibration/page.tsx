import type { Metadata } from "next";
import { Crosshair } from "lucide-react";

import { ModulePlaceholder } from "@/components/layout/module-placeholder";

export const metadata: Metadata = { title: "Calibration" };

export default function Page() {
  return (
    <ModulePlaceholder
      eyebrow="Évaluer"
      title="Calibration"
      icon={<Crosshair />}
      description="Accord entre juges IA et évaluations humaines, par juge et par critère."
      upcoming={[
        "Taux d'accord, écart moyen, Spearman, Pearson, kappa pondéré",
        "Statut : calibré, faible, non calibré, données insuffisantes",
        "Gold datasets",
      ]}
    />
  );
}
