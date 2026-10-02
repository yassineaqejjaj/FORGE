import type { Metadata } from "next";
import { Suspense } from "react";

import { ReviewQueueView } from "@/components/reviews/review-queue-view";

export const metadata: Metadata = { title: "Revue humaine" };

export default function ReviewsPage() {
  return (
    <Suspense fallback={null}>
      <ReviewQueueView />
    </Suspense>
  );
}
