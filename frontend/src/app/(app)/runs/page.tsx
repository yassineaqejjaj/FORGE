import type { Metadata } from "next";
import { Suspense } from "react";

import { RunsListView } from "@/components/runs/runs-list-view";

export const metadata: Metadata = { title: "Runs" };

export default function RunsPage() {
  return (
    <Suspense fallback={null}>
      <RunsListView />
    </Suspense>
  );
}
