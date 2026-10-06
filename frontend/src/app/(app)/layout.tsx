"use client";

import * as React from "react";
import { RefreshCw, ServerCrash } from "lucide-react";

import { ForgeLogo } from "@/components/brand/forge-logo";
import { AppHeader } from "@/components/layout/app-header";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { CommandPalette } from "@/components/layout/command-palette";
import { MobileNav } from "@/components/layout/mobile-nav";
import { MobileTabBar } from "@/components/layout/mobile-tab-bar";
import { ShellProvider } from "@/components/layout/shell-context";
import { SplashScreen } from "@/components/layout/splash-screen";
import { Button } from "@/components/ui/button";
import { useMe } from "@/lib/api/auth";
import { errorMessage } from "@/lib/api/client";

function BackendUnavailable({ error, onRetry, retrying }: { error: unknown; onRetry: () => void; retrying: boolean }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-background px-4 text-center">
      <ForgeLogo />
      <div className="grid max-w-md justify-items-center gap-3">
        <span className="flex size-11 items-center justify-center rounded-xl border border-border bg-card text-destructive shadow-xs">
          <ServerCrash className="size-5" aria-hidden />
        </span>
        <h1 className="text-lg font-semibold tracking-tight">Service FORGE indisponible</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">{errorMessage(error)}</p>
        <Button onClick={onRetry} loading={retrying} leftIcon={<RefreshCw aria-hidden />}>
          Réessayer
        </Button>
      </div>
    </div>
  );
}

/** Authenticated application shell: session bootstrap (GET /auth/me), sidebar, header, command palette. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const me = useMe();

  if (me.isPending) return <SplashScreen />;
  if (me.isError) {
    // 401 → the API client already redirects to /login?next=…
    if (me.error.isUnauthorized) return <SplashScreen label="Redirection vers la connexion…" />;
    return <BackendUnavailable error={me.error} onRetry={() => void me.refetch()} retrying={me.isFetching} />;
  }

  return (
    <ShellProvider>
      <a
        href="#main-content"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Aller au contenu
      </a>
      <div className="flex min-h-dvh bg-background">
        <AppSidebar />
        <MobileNav />
        <MobileTabBar />
        <div className="flex min-w-0 flex-1 flex-col">
          <AppHeader />
          <main id="main-content" tabIndex={-1} className="flex-1 focus:outline-none">
            {/* Content column (design system): 1180px, 20–32px gutters, 32–40px vertical; room for the mobile tab bar */}
            <div className="mx-auto w-full max-w-[1180px] px-5 pb-24 pt-8 md:px-8 lg:pb-10 lg:pt-10">{children}</div>
          </main>
        </div>
      </div>
      <CommandPalette />
    </ShellProvider>
  );
}
