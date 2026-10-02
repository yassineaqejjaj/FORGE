import type { Metadata } from "next";

import { JudgeDetailView } from "@/components/judges/judge-detail-view";

export const metadata: Metadata = { title: "Juge" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <JudgeDetailView id={id} />;
}
