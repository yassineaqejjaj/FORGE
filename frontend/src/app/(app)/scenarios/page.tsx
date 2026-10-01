import type { Metadata } from "next";
import { ScrollText } from "lucide-react";

import { ModulePlaceholder } from "@/components/layout/module-placeholder";

export const metadata: Metadata = { title: "Scénarios" };

export default function Page() {
  return (
    <ModulePlaceholder
      eyebrow="Laboratoire"
      title="Scénarios"
      icon={<ScrollText />}
      description="Bibliothèque de scénarios versionnés : publics, privés (cachés) et fresh, avec variantes."
      upcoming={[
        "Éditeur de scénario (entrée, contexte, contraintes, résultat attendu, règles)",
        "Versions, variantes et familles",
        "Import / export",
        "Classification C0–C3 et contenu masqué des scénarios privés",
      ]}
    />
  );
}
