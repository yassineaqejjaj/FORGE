import type { Metadata } from "next";
import { Suspense } from "react";

import { ExperimentDetailView } from "@/components/experiments/experiment-detail-view";

export const metadata: Metadata = { title: "Expérience" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <ExperimentDetailView id={id} />
    </Suspense>
  );
}
