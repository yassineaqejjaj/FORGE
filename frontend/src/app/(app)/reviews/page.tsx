import type { Metadata } from "next";
import { ClipboardCheck } from "lucide-react";

import { ModulePlaceholder } from "@/components/layout/module-placeholder";

export const metadata: Metadata = { title: "Revue humaine" };

export default function Page() {
  return (
    <ModulePlaceholder
      eyebrow="Évaluer"
      title="Revue humaine"
      icon={<ClipboardCheck />}
      description="File de revue priorisée par désaccord des juges et évaluations humaines."
      upcoming={[
        "File de revue (apprentissage actif)",
        "Notation par critère avec justification",
        "Historique des évaluations humaines d'un run",
      ]}
    />
  );
}
