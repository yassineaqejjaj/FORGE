import type { Metadata } from "next";
import { Suspense } from "react";

import { BenchmarksListView } from "@/components/benchmarks/benchmarks-list-view";

export const metadata: Metadata = { title: "Benchmarks" };

export default function Page() {
  return (
    <Suspense>
      <BenchmarksListView />
    </Suspense>
  );
}
