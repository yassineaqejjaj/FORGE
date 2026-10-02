import type { Metadata } from "next";
import { Suspense } from "react";

import { BenchmarkDetailView } from "@/components/benchmarks/benchmark-detail-view";

export const metadata: Metadata = { title: "Benchmark" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <BenchmarkDetailView id={id} />
    </Suspense>
  );
}
