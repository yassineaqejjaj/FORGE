"use client";

import { LocalTabs } from "@/components/layout/local-tabs";
import { JUDGES_AREA_TABS, RESULTS_AREA_TABS } from "@/components/layout/nav";

/** Configuration › Juges : juges, configurations de score et calibration (one area, local tabs). */
export function JudgesAreaTabs() {
  return <LocalTabs label="Sections des juges" tabs={JUDGES_AREA_TABS.map((t) => ({ href: t.href, label: t.label }))} />;
}

/** Analyser › Résultats : synthèse par version et erreurs détectées. */
export function ResultsAreaTabs() {
  return <LocalTabs label="Sections des résultats" tabs={RESULTS_AREA_TABS.map((t) => ({ href: t.href, label: t.label }))} />;
}
