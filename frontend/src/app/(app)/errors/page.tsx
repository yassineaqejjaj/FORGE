import type { Metadata } from "next";
import { Bug } from "lucide-react";

import { ModulePlaceholder } from "@/components/layout/module-placeholder";

export const metadata: Metadata = { title: "Erreurs" };

export default function Page() {
  return (
    <ModulePlaceholder
      eyebrow="Évaluer"
      title="Erreurs"
      icon={<Bug />}
      description="Explorateur des erreurs détectées par type, gravité, agent et scénario."
      upcoming={[
        "Filtres par type, gravité, agent, scénario, période",
        "Agrégations et tendances",
        "Accès direct aux preuves dans la trace",
      ]}
    />
  );
}
