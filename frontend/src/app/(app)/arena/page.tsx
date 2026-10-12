import type { Metadata } from "next";
import { Suspense } from "react";

import { ArenaView } from "@/components/arena/arena-view";

export const metadata: Metadata = { title: "Arène des modèles" };

export default function ArenaPage() {
  return (
    <Suspense fallback={null}>
      <ArenaView />
    </Suspense>
  );
}
