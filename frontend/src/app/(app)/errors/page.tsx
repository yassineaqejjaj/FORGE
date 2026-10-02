import type { Metadata } from "next";
import { Suspense } from "react";

import { ErrorsExplorerView } from "@/components/errors/errors-explorer-view";

export const metadata: Metadata = { title: "Erreurs détectées" };

export default function ErrorsPage() {
  return (
    <Suspense fallback={null}>
      <ErrorsExplorerView />
    </Suspense>
  );
}
