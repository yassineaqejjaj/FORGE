import type { Metadata } from "next";
import { Suspense } from "react";

import { ConfigsListView } from "@/components/evaluation-configs/configs-list-view";

export const metadata: Metadata = { title: "Configurations d'évaluation" };

export default function Page() {
  return (
    <Suspense>
      <ConfigsListView />
    </Suspense>
  );
}
