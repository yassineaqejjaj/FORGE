import { Suspense } from "react";
import type { Metadata } from "next";

import { CompareView } from "@/components/agents/compare-view";

export const metadata: Metadata = { title: "Comparer des versions" };

export default async function CompareVersionsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <CompareView agentId={id} />
    </Suspense>
  );
}
