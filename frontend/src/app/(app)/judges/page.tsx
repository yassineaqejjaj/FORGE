import type { Metadata } from "next";
import { Suspense } from "react";

import { JudgesListView } from "@/components/judges/judges-list-view";

export const metadata: Metadata = { title: "Juges" };

export default function Page() {
  return (
    <Suspense>
      <JudgesListView />
    </Suspense>
  );
}
