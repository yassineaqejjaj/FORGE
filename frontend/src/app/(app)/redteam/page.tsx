import type { Metadata } from "next";
import { Suspense } from "react";

import { RedTeamView } from "@/components/redteam/redteam-view";

export const metadata: Metadata = { title: "Red team" };

export default function RedTeamPage() {
  return (
    <Suspense fallback={null}>
      <RedTeamView />
    </Suspense>
  );
}
