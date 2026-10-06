"use client";

import * as React from "react";
import { Search } from "lucide-react";

import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { useShell } from "@/components/layout/shell-context";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { UserMenu } from "@/components/layout/user-menu";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { modKeyLabel } from "@/lib/utils";

/** Sticky top bar: breadcrumb, search pill (⌘K), theme toggle, user menu. Mobile navigation is the bottom tab bar. */
export function AppHeader() {
  const { openCommandPalette } = useShell();
  const [mod, setMod] = React.useState("⌘");
  React.useEffect(() => setMod(modKeyLabel()), []);

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-border bg-background/85 px-3 backdrop-blur supports-[backdrop-filter]:bg-background/70 sm:px-4 lg:px-6">
      <Breadcrumbs className="min-w-0 flex-1" />

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={openCommandPalette}
          className="hidden h-8 w-56 items-center gap-2 rounded-full bg-surface-2/80 px-3.5 text-[13px] text-subtle-foreground transition-colors hover:bg-surface-2 hover:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 md:flex xl:w-64"
          aria-label="Aller à une page ou lancer une action (raccourci ⌘K ou Ctrl+K)"
          aria-keyshortcuts="Meta+K Control+K"
        >
          <Search className="size-3.5" aria-hidden />
          <span className="flex-1 text-left">Rechercher</span>
          <span className="flex items-center gap-0.5" aria-hidden>
            <Kbd>{mod}</Kbd>
            <Kbd>K</Kbd>
          </span>
        </button>
        <Button variant="ghost" size="icon-sm" className="md:hidden" onClick={openCommandPalette} aria-label="Aller à une page">
          <Search aria-hidden />
        </Button>
        <ThemeToggle />
        <UserMenu />
      </div>
    </header>
  );
}
