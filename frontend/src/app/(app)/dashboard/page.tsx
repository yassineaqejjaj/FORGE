import { Suspense } from "react";
import type { Metadata } from "next";

import { DashboardView } from "@/components/dashboard/dashboard-view";

/** The home of the app: the tab shows the product name alone. */
export const metadata: Metadata = { title: { absolute: "FORGE" } };

export default function DashboardPage() {
  return (
    <Suspense>
      <DashboardView />
    </Suspense>
  );
}
