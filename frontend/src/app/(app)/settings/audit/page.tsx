import type { Metadata } from "next";
import { Anvil } from "lucide-react";

import { RoleGate } from "@/components/auth/require-role";
import { EmptyState } from "@/components/ui/empty-state";

export const metadata: Metadata = { title: "Audit · Paramètres" };

export default function Page() {
  return (
    <RoleGate min="maintainer">
      <section aria-labelledby="settings-section-title" className="grid gap-4">
        <div className="grid gap-1">
          <h2 id="settings-section-title" className="text-base font-semibold tracking-tight">
            Audit
          </h2>
          <p className="text-sm text-muted-foreground">Journal de toutes les mutations : acteur, action, cible, date.</p>
        </div>
        <EmptyState
          icon={<Anvil />}
          title="Module en cours d'intégration"
          description="Cette section est en cours de forge et sera disponible prochainement."
        >
          <ul className="mt-2 grid max-w-md gap-1.5 text-left text-[13px] text-muted-foreground">
            {[
            "Filtres par acteur, action, cible et période",
            "Détail de chaque entrée",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand" aria-hidden />
                {item}
              </li>
            ))}
          </ul>
        </EmptyState>
      </section>
    </RoleGate>
  );
}
