import type { Metadata } from "next";
import { Suspense } from "react";

import { CalibrationView } from "@/components/calibration/calibration-view";

export const metadata: Metadata = { title: "Calibration" };

export default function CalibrationPage() {
  return (
    <Suspense fallback={null}>
      <CalibrationView />
    </Suspense>
  );
}
