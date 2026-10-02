"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { ChevronDown } from "lucide-react";

import { ForgeLogo } from "@/components/brand/forge-logo";
import { NavBadgePill, useActiveHref, useVisibleSections } from "@/components/layout/app-sidebar";
import { ContextSwitcher } from "@/components/layout/context-switcher";
import { activeNav, isViewActive, type NavItem, type NavSection, type NavSectionId, type NavSubPage } from "@/components/layout/nav";
import { useShell } from "@/components/layout/shell-context";
import { useNavBadges, type NavBadge } from "@/components/layout/use-nav-badges";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

const ROW = "flex min-h-11 w-full items-center gap-3 rounded-lg px-3 text-[15px] transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function useSubPageActive(): (sub: NavSubPage) => boolean {
  const pathname = usePathname();
  const params = useSearchParams();
  return (sub) => isViewActive(pathname, new URLSearchParams(params.toString()), sub.href);
}

function MobileLink({
  href,
  label,
  icon: Icon,
  active,
  badge,
  nested = false,
  onNavigate,
}: {
  href: string;
  label: string;
  icon?: NavItem["icon"];
  active: boolean;
  badge?: NavBadge;
  nested?: boolean;
  onNavigate: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      aria-label={badge ? `${label} — ${badge.label}` : undefined}
      className={cn(
        ROW,
        nested && "pl-11 text-[14.5px]",
        active ? "bg-brand-soft font-semibold text-brand" : "font-medium text-sidebar-foreground hover:bg-sidebar-accent",
      )}
    >
      {Icon ? <Icon className={cn("size-[18px] shrink-0", active ? "text-brand" : "text-sidebar-muted")} aria-hidden /> : null}
      <span className="truncate">{label}</span>
      {badge ? <NavBadgePill badge={badge} /> : null}
    </Link>
  );
}

function CategoryPanel({
  section,
  open,
  onToggle,
  activeHref,
  badges,
  onNavigate,
}: {
  section: NavSection;
  open: boolean;
  onToggle: () => void;
  activeHref?: string;
  badges: ReturnType<typeof useNavBadges>;
  onNavigate: () => void;
}) {
  const isSubActive = useSubPageActive();
  const Icon = section.icon;
  const panelId = `mobile-nav-${section.id}`;
  const containsActive = section.items.some((i) => i.href === activeHref);
  const sectionBadge = section.items.map((i) => (i.badge ? badges[i.badge] : undefined)).find(Boolean);

  return (
    <li>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={panelId}
        className={cn(ROW, "font-semibold", containsActive ? "text-brand" : "text-sidebar-accent-foreground", "hover:bg-sidebar-accent")}
      >
        <Icon className={cn("size-[18px] shrink-0", containsActive ? "text-brand" : "text-sidebar-muted")} aria-hidden />
        <span className="grid min-w-0 flex-1 text-left leading-tight">
          <span className="truncate">{section.label}</span>
          <span className="truncate text-[12px] font-normal text-sidebar-muted">{section.hint}</span>
        </span>
        {!open && sectionBadge ? <NavBadgePill badge={sectionBadge} className="ml-0" /> : null}
        <ChevronDown
          className={cn("size-4 shrink-0 text-sidebar-muted transition-transform duration-200 motion-reduce:transition-none", open && "rotate-180")}
          aria-hidden
        />
      </button>
      <div
        id={panelId}
        role="region"
        aria-label={section.label}
        hidden={!open}
        className="pb-1"
      >
        <ul className="grid gap-0.5 pt-0.5">
          {section.items.map((item) =>
            item.children?.length ? (
              item.children.map((child, index) => (
                <li key={child.href}>
                  <MobileLink
                    href={child.href}
                    label={index === 0 ? "Toutes les exécutions" : child.label}
                    active={isSubActive(child)}
                    badge={child.href.endsWith("status=failed") && item.badge ? badges[item.badge] : undefined}
                    nested
                    onNavigate={onNavigate}
                  />
                </li>
              ))
            ) : (
              <li key={item.href}>
                <MobileLink
                  href={item.href}
                  label={item.label}
                  active={item.href === activeHref}
                  badge={item.badge ? badges[item.badge] : undefined}
                  nested
                  onNavigate={onNavigate}
                />
              </li>
            ),
          )}
        </ul>
      </div>
    </li>
  );
}

function MobileNavBody({ onNavigate }: { onNavigate: () => void }) {
  const pathname = usePathname();
  const sections = useVisibleSections();
  const activeHref = useActiveHref();
  const badges = useNavBadges();
  const activeSection = activeNav(pathname)?.section.id;
  // Reopening the drawer shows the category of the current page.
  const [open, setOpen] = React.useState<NavSectionId | undefined>(activeSection);

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-col gap-3 px-4 pb-3 pt-4">
        <Link href="/dashboard" onClick={onNavigate} className="w-fit rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="FORGE — vue d'ensemble">
          <ForgeLogo />
        </Link>
        <ContextSwitcher onNavigate={onNavigate} />
      </div>
      <nav className="flex-1 overflow-y-auto overscroll-contain px-3 pb-6" aria-label="Navigation principale">
        <ul className="grid gap-0.5">
          {sections.map((section) =>
            !section.heading ? (
              section.items.map((item) => (
                <li key={item.href}>
                  <MobileLink
                    href={item.href}
                    label={item.label}
                    icon={item.icon}
                    active={item.href === activeHref}
                    onNavigate={onNavigate}
                  />
                </li>
              ))
            ) : (
              <CategoryPanel
                key={section.id}
                section={section}
                open={open === section.id}
                onToggle={() => setOpen((current) => (current === section.id ? undefined : section.id))}
                activeHref={activeHref}
                badges={badges}
                onNavigate={onNavigate}
              />
            ),
          )}
        </ul>
      </nav>
    </div>
  );
}

/** Compact drawer below the lg breakpoint: intent categories, one open at a time. */
export function MobileNav() {
  const { mobileNavOpen, setMobileNavOpen } = useShell();
  const pathname = usePathname();
  // After choosing a destination, focus goes to the new page, not back to the menu button.
  const navigated = React.useRef(false);
  const close = React.useCallback(() => {
    navigated.current = true;
    setMobileNavOpen(false);
  }, [setMobileNavOpen]);

  React.useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname, setMobileNavOpen]);

  return (
    <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
      <SheetContent
        side="left"
        size="sm"
        className="w-[min(88vw,340px)] bg-sidebar p-0 lg:hidden"
        onCloseAutoFocus={(event) => {
          if (!navigated.current) return;
          navigated.current = false;
          event.preventDefault();
          document.getElementById("main-content")?.focus({ preventScroll: true });
        }}
      >
        <SheetTitle className="sr-only">Navigation</SheetTitle>
        <SheetDescription className="sr-only">Navigation principale de FORGE : concevoir, tester, analyser, améliorer</SheetDescription>
        <React.Suspense fallback={null}>
          {mobileNavOpen ? <MobileNavBody onNavigate={close} /> : null}
        </React.Suspense>
      </SheetContent>
    </Sheet>
  );
}
