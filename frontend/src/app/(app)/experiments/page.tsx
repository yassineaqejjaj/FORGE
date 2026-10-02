import type { Metadata } from "next";
import { Suspense } from "react";

import { ExperimentsListView } from "@/components/experiments/experiments-list-view";

export const metadata: Metadata = { title: "Expériences" };

export default function Page() {
  return (
    <Suspense>
      <ExperimentsListView />
    </Suspense>
  );
}
