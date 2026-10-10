"use client";

import * as React from "react";

const SIDEBAR_STORAGE_KEY = "forge-sidebar-collapsed";

interface ShellContextValue {
  openCommandPalette: () => void;
  closeCommandPalette: () => void;
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (open: boolean) => void;
  mobileNavOpen: boolean;
  setMobileNavOpen: (open: boolean) => void;
  /** Welcome tour opened on demand (« Visite guidée » in the user menu); the first-login tour opens by itself. */
  onboardingReplayOpen: boolean;
  setOnboardingReplayOpen: (open: boolean) => void;
  /** Desktop sidebar reduced to an icon rail (persisted per browser). */
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
  /** Custom breadcrumb labels keyed by route segment value (e.g. a run id → its label). */
  crumbLabels: Record<string, string>;
  setCrumbLabel: (key: string, label: string | null) => void;
}

const ShellContext = React.createContext<ShellContextValue | null>(null);

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function ShellProvider({ children }: { children: React.ReactNode }) {
  const [commandPaletteOpen, setCommandPaletteOpen] = React.useState(false);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const [onboardingReplayOpen, setOnboardingReplayOpen] = React.useState(false);
  const [sidebarCollapsed, setCollapsedState] = React.useState(false);
  const [crumbLabels, setCrumbLabels] = React.useState<Record<string, string>>({});

  React.useEffect(() => {
    setCollapsedState(readCollapsed());
  }, []);

  const setSidebarCollapsed = React.useCallback((collapsed: boolean) => {
    setCollapsedState(collapsed);
    try {
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? "1" : "0");
    } catch {
      // storage unavailable: keep the in-memory state
    }
  }, []);

  const toggleSidebar = React.useCallback(() => {
    setCollapsedState((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(SIDEBAR_STORAGE_KEY, next ? "1" : "0");
      } catch {
        // ignore
      }
      return next;
    });
  }, []);

  const setCrumbLabel = React.useCallback((key: string, label: string | null) => {
    setCrumbLabels((prev) => {
      if (label === null) {
        if (!(key in prev)) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      }
      if (prev[key] === label) return prev;
      return { ...prev, [key]: label };
    });
  }, []);

  const value = React.useMemo<ShellContextValue>(
    () => ({
      openCommandPalette: () => setCommandPaletteOpen(true),
      closeCommandPalette: () => setCommandPaletteOpen(false),
      commandPaletteOpen,
      setCommandPaletteOpen,
      mobileNavOpen,
      setMobileNavOpen,
      onboardingReplayOpen,
      setOnboardingReplayOpen,
      sidebarCollapsed,
      setSidebarCollapsed,
      toggleSidebar,
      crumbLabels,
      setCrumbLabel,
    }),
    [commandPaletteOpen, mobileNavOpen, onboardingReplayOpen, sidebarCollapsed, setSidebarCollapsed, toggleSidebar, crumbLabels, setCrumbLabel],
  );

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

export function useShell(): ShellContextValue {
  const ctx = React.useContext(ShellContext);
  if (!ctx) throw new Error("useShell must be used within <ShellProvider>");
  return ctx;
}

/**
 * Sets a human label for a dynamic route segment in the header breadcrumb while mounted.
 * Example (run page): useBreadcrumbLabel(runId, `${scenario.name} · ${agent.name}`)
 */
export function useBreadcrumbLabel(segmentValue: string | undefined, label: string | null | undefined) {
  const ctx = React.useContext(ShellContext);
  const setCrumbLabel = ctx?.setCrumbLabel;
  React.useEffect(() => {
    if (!setCrumbLabel || !segmentValue || !label) return;
    setCrumbLabel(segmentValue, label);
    return () => setCrumbLabel(segmentValue, null);
  }, [setCrumbLabel, segmentValue, label]);
}
