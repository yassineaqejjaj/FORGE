import type { Metadata } from "next";
import { FlaskConical } from "lucide-react";

import { ModulePlaceholder } from "@/components/layout/module-placeholder";

export const metadata: Metadata = { title: "Expériences" };

export default function Page() {
  return (
    <ModulePlaceholder
      eyebrow="Comparer"
      title="Expériences"
      icon={<FlaskConical />}
      description="Baseline vs candidate sur les mêmes scénarios : verdicts, régressions et recommandation."
      upcoming={[
        "Comparaison par dimension (delta, IC apparié, Wilcoxon)",
        "Régressions et améliorations par scénario",
        "Recommandation : déployer, avec prudence, ne pas déployer",
        "Garde-fou CI (gate)",
      ]}
    />
  );
}
