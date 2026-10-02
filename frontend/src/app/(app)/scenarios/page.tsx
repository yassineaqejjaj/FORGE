import { Suspense } from "react";
import type { Metadata } from "next";

import { ScenariosListView } from "@/components/scenarios/scenarios-list-view";

export const metadata: Metadata = { title: "Scénarios" };

export default function ScenariosPage() {
  return (
    <Suspense>
      <ScenariosListView />
    </Suspense>
  );
}
