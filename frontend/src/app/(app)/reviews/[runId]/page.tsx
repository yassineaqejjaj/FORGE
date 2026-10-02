import type { Metadata } from "next";
import { Suspense } from "react";

import { ReviewWorkspaceView } from "@/components/reviews/review-workspace-view";

export const metadata: Metadata = { title: "Évaluer un run" };

export default async function ReviewWorkspacePage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return (
    <Suspense fallback={null}>
      <ReviewWorkspaceView runId={runId} />
    </Suspense>
  );
}
