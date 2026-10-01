import type { Metadata } from "next";
import { Gavel } from "lucide-react";

import { ModulePlaceholder } from "@/components/layout/module-placeholder";

export const metadata: Metadata = { title: "Juges" };

export default function Page() {
  return (
    <ModulePlaceholder
      eyebrow="Évaluer"
      title="Juges"
      icon={<Gavel />}
      description="Juges LLM et heuristiques, versionnés, avec leurs prompts et rubriques."
      upcoming={[
        "Création et versions de juges",
        "Activation / désactivation",
        "Test d'un juge sur un run",
        "Calibration associée",
      ]}
    />
  );
}
