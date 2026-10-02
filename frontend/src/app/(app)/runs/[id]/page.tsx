import type { Metadata } from "next";
import { Suspense } from "react";

import { RunDetailView } from "@/components/runs/detail/run-detail-view";

export const metadata: Metadata = { title: "Exécution" };

export default async function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense fallback={null}>
      <RunDetailView id={id} />
    </Suspense>
  );
}
