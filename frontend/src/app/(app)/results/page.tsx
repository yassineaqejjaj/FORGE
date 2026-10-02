import type { Metadata } from "next";
import { Suspense } from "react";

import { ResultsOverviewView } from "@/components/results/results-overview-view";

export const metadata: Metadata = { title: "Résultats" };

export default function ResultsPage() {
  return (
    <Suspense fallback={null}>
      <ResultsOverviewView />
    </Suspense>
  );
}
