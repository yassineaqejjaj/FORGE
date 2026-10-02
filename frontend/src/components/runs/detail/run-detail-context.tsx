"use client";

import * as React from "react";

export interface RunDetailContextValue {
  runId: string;
  /** Evaluation round displayed (null = latest). */
  round: number | null;
  /** Trace event currently highlighted in the timeline. */
  highlightedSeq: number | null;
  /** Increments on every focus request (re-triggers scrolling to the same event). */
  focusNonce: number;
  /** Scroll the timeline to an event and highlight it (switches to the execution tab on small screens). */
  focusEvent: (seq: number) => void;
  /** Open the detail drawer of an event. */
  openEvent: (seq: number) => void;
  /** Open the provenance sheet of a criterion score. */
  openProvenance: (criterionKey: string) => void;
  /** Short label of an event ("Appel au modèle — Génération"), when the timeline is loaded. */
  eventLabel: (seq: number) => string | undefined;
}

const RunDetailContext = React.createContext<RunDetailContextValue | null>(null);

export function RunDetailProvider({ value, children }: { value: RunDetailContextValue; children: React.ReactNode }) {
  return <RunDetailContext.Provider value={value}>{children}</RunDetailContext.Provider>;
}

/** Run Detail interactions; null outside a Run Detail page (e.g. review workspace). */
export function useRunDetail(): RunDetailContextValue | null {
  return React.useContext(RunDetailContext);
}
