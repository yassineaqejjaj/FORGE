"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";

import { isActiveHref } from "@/components/layout/nav";
import { cn } from "@/lib/utils";

export interface LocalTab {
  href: string;
  label: string;
  icon?: LucideIcon;
  /** Explicit active state (query-driven tabs); defaults to a pathname match. */
  active?: boolean;
  /** Small counter or hint rendered after the label. */
  suffix?: React.ReactNode;
}

const TAB_CLASSES =
  "inline-flex h-9 items-center gap-2 whitespace-nowrap border-b-2 px-3 text-[13px] font-medium transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset";

/**
 * Secondary navigation of an area or an object (Paramètres, Juges, Résultats, Exécutions…).
 * Functions that belong to a page live here, never in the sidebar, so the sidebar stays stable
 * when FORGE grows. Rendered inside `PageHeader` (its bottom border aligns with the header).
 */
export function LocalTabs({
  tabs,
  label,
  onSelect,
  className,
}: {
  tabs: LocalTab[];
  /** Accessible name of the tab bar (« Sections des paramètres »). */
  label: string;
  /** Query-driven tabs: intercept the click (the href stays a real, shareable link). */
  onSelect?: (tab: LocalTab, event: React.MouseEvent<HTMLAnchorElement>) => void;
  className?: string;
}) {
  const pathname = usePathname();
  // The longest matching href wins so that « /judges » is not active on « /judges-x ».
  const pathActive = tabs
    .filter((t) => t.active === undefined && isActiveHref(pathname, t.href))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;

  return (
    <nav aria-label={label} className={cn("-mb-px overflow-x-auto border-b border-border [scrollbar-width:none]", className)}>
      <ul className="flex min-w-max gap-1">
        {tabs.map((tab) => {
          const active = tab.active ?? tab.href === pathActive;
          const Icon = tab.icon;
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                aria-current={active ? "page" : undefined}
                onClick={onSelect ? (event) => onSelect(tab, event) : undefined}
                className={cn(
                  TAB_CLASSES,
                  active
                    ? "border-brand text-foreground"
                    : "border-transparent text-muted-foreground hover:border-border-strong hover:text-foreground",
                )}
              >
                {Icon ? <Icon className="size-4" aria-hidden /> : null}
                {tab.label}
                {tab.suffix}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
