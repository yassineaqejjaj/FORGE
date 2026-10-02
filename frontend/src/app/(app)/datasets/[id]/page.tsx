import type { Metadata } from "next";

import { DatasetDetailView } from "@/components/datasets/dataset-detail-view";

export const metadata: Metadata = { title: "Dataset" };

export default async function DatasetPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <DatasetDetailView id={id} />;
}
