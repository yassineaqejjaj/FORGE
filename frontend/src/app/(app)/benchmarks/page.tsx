import type { Metadata } from "next";
import { Layers } from "lucide-react";

import { ModulePlaceholder } from "@/components/layout/module-placeholder";

export const metadata: Metadata = { title: "Benchmarks" };

export default function Page() {
  return (
    <ModulePlaceholder
      eyebrow="Comparer"
      title="Benchmarks"
      icon={<Layers />}
      description="Matrices scénarios × versions d'agents × répétitions, classements et robustesse."
      upcoming={[
        "Définition et lancement d'un benchmark",
        "Classement avec IC 95 %, taux de réussite, coûts, latences",
        "Matrice scénario × agent, écart de généralisation",
        "Rapports de feedback par version",
      ]}
    />
  );
}
