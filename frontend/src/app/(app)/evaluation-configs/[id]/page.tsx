import type { Metadata } from "next";

import { ConfigDetailView } from "@/components/evaluation-configs/config-detail-view";

export const metadata: Metadata = { title: "Configuration de score" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ConfigDetailView id={id} />;
}
