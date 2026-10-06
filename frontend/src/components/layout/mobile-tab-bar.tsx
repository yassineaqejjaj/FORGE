"use client";

import Link from "next/link";
import { BarChart3, FlaskConical, LayoutDashboard, Menu, Play, type LucideIcon } from "lucide-react";

import { useActiveHref } from "@/components/layout/app-sidebar";
import { useShell } from "@/components/layout/shell-context";
import { cn } from "@/lib/utils";

/** The four destinations used most on a phone; « Menu » opens the full navigation. */
const TABS: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/dashboard", label: "Vue d'ensemble", icon: LayoutDashboard },
  { href: "/runs", label: "Exécutions", icon: Play },
  { href: "/results", label: "Résultats", icon: BarChart3 },
  { href: "/experiments", label: "Expériences", icon: FlaskConical },
];

const TAB_CLASSES =
  "flex min-w-0 flex-1 flex-col items-center justify-center gap-1 rounded-lg text-[11px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50";

/** Mobile navigation (< lg): fixed bottom tab bar, 64px, blurred surface (design system). */
export function MobileTabBar() {
  const activeHref = useActiveHref();
  const { mobileNavOpen, setMobileNavOpen } = useShell();
  return (
    <nav
      aria-label="Navigation principale (mobile)"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
    >
      <ul className="mx-auto flex h-16 max-w-xl items-stretch gap-1 px-2 py-1.5">
        {TABS.map((tab) => {
          const active = tab.href === activeHref;
          const Icon = tab.icon;
          return (
            <li key={tab.href} className="flex flex-1">
              <Link
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={cn(TAB_CLASSES, active ? "text-brand" : "text-muted-foreground hover:text-foreground")}
              >
                <Icon className="size-5" aria-hidden />
                <span className="max-w-full truncate">{tab.label}</span>
              </Link>
            </li>
          );
        })}
        <li className="flex flex-1">
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            aria-expanded={mobileNavOpen}
            aria-haspopup="dialog"
            className={cn(TAB_CLASSES, "text-muted-foreground hover:text-foreground")}
          >
            <Menu className="size-5" aria-hidden />
            <span>Menu</span>
          </button>
        </li>
      </ul>
    </nav>
  );
}
