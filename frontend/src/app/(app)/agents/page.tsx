import { Suspense } from "react";
import type { Metadata } from "next";

import { AgentsListView } from "@/components/agents/agents-list-view";

export const metadata: Metadata = { title: "Agents" };

export default function AgentsPage() {
  return (
    <Suspense>
      <AgentsListView />
    </Suspense>
  );
}
