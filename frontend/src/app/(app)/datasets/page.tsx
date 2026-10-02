import type { Metadata } from "next";
import { Suspense } from "react";

import { DatasetsListView } from "@/components/datasets/datasets-list-view";

export const metadata: Metadata = { title: "Datasets" };

export default function DatasetsPage() {
  return (
    <Suspense fallback={null}>
      <DatasetsListView />
    </Suspense>
  );
}
