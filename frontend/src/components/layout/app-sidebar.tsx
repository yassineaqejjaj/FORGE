"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { ForgeLogo, ForgeMark } from "@/components/brand/forge-logo";
import { ContextSwitcher } from "@/components/layout/context-switcher";
import { activeNav, NAV_SECTIONS, type NavItem, type NavSection } from "@/components/layout/nav";
import { useShell } from "@/components/layout/shell-context";
import { formatBadgeCount, useNavBadges, type NavBadge } from "@/components/layout/use-nav-badges";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useCurrentUser } from "@/hooks/use-current-user";
import { http, isApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";

/** Sections visible to the current user (role-filtered, empty sections dropped). */
export function useVisibleSections(): NavSection[] {
  const { hasRole } = useCurrentUser();
  return NAV_SECTIONS.map((s) => ({ ...s, items: s.items.filter((i) => !i.minRole || hasRole(i.minRole)) })).filter(
    (s) => s.items.length > 0,
  );
}

/** Href of the active entry (its own route or one of its local tabs). */
export function useActiveHref(): string | undefined {
  const pathname = usePathname();
  return activeNav(pathname)?.item.href;
}

const BADGE_TONES: Record<NavBadge["tone"], string> = {
  red: "bg-red-500/12 text-red-700 dark:bg-red-400/15 dark:text-red-300",
  brand: "bg-brand/12 text-brand",
};

export function NavBadgePill({ badge, className }: { badge: NavBadge; className?: string }) {
  return (
    <span
      className={cn(
        "ml-auto inline-flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-full px-1.5 text-[10.5px] font-semibold tabular-nums",
        BADGE_TONES[badge.tone],
        className,
      )}
      aria-hidden
    >
      {formatBadgeCount(badge.count)}
    </span>
  );
}

function NavLink({
  item,
  active,
  collapsed,
  badge,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  badge?: NavBadge;
}) {
  const Icon = item.icon;
  const accessibleName = badge ? `${item.label} — ${badge.label}` : item.label;
  const link = (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed || badge ? accessibleName : undefined}
      className={cn(
        "group relative flex h-[30px] items-center gap-2.5 rounded-md text-[13px] transition-colors duration-150 motion-reduce:transition-none",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        collapsed ? "justify-center px-0" : "px-2",
        active
          ? "bg-brand-soft font-semibold text-brand"
          : "font-medium text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
      )}
    >
      <Icon
        className={cn(
          "size-[15px] shrink-0 transition-colors motion-reduce:transition-none",
          active ? "text-brand" : "text-sidebar-muted/80 group-hover:text-sidebar-foreground",
        )}
        aria-hidden
      />
      {!collapsed ? <span className="truncate">{item.label}</span> : null}
      {!collapsed && badge ? <NavBadgePill badge={badge} /> : null}
      {collapsed && badge ? (
        <span
          className={cn("absolute right-1.5 top-1 size-1.5 rounded-full", badge.tone === "red" ? "bg-red-500" : "bg-brand")}
          aria-hidden
        />
      ) : null}
    </Link>
  );
  if (!collapsed) return link;
  return (
    <SimpleTooltip content={badge ? accessibleName : item.label} side="right">
      {link}
    </SimpleTooltip>
  );
}

/** « 1.0.0 » → « 1.0 » (the patch number is noise in the navigation). */
function shortVersion(version: string): string {
  const [major, minor] = version.split(".");
  return minor !== undefined ? `${major}.${minor}` : version;
}

/**
 * API reachability, kept discreet: a dot and one word; details in the tooltip.
 * `/meta` is only read for its optional `version` string.
 */
function SystemStatus({ collapsed }: { collapsed: boolean }) {
  const meta = useQuery({
    queryKey: queryKeys.meta(),
    queryFn: ({ signal }) => http.get<Record<string, unknown>>("/meta", { signal }),
    staleTime: 5 * 60_000,
    retry: false,
  });
  // Any HTTP answer below 500 proves the API is up.
  const reachable =
    meta.isSuccess ||
    (meta.isError && isApiError(meta.error) && meta.error.status > 0 && (meta.error.status < 500 || meta.error.isNotImplemented));
  const version = meta.isSuccess && typeof meta.data?.version === "string" ? meta.data.version : null;
  const label = meta.isPending ? "Connexion…" : reachable ? "Opérationnel" : "API injoignable";
  const detail = reachable
    ? `Plateforme opérationnelle — API FORGE joignable${version ? ` · version ${version}` : ""}`
    : meta.isError
      ? "Le backend FORGE ne répond pas."
      : "Connexion à l'API…";
  return (
    <SimpleTooltip content={detail} side={collapsed ? "right" : "top"} align="start">
      <div
        className={cn("flex min-w-0 items-center gap-2 text-[11.5px] text-sidebar-muted", collapsed && "justify-center")}
        tabIndex={0}
        role="status"
        aria-label={detail}
      >
        <span
          className={cn(
            "inline-flex size-1.5 shrink-0 rounded-full",
            meta.isPending ? "bg-stone-400" : reachable ? "bg-emerald-500" : "bg-red-500",
          )}
          aria-hidden
        />
        {!collapsed ? <span className="truncate">{label}</span> : null}
        {!collapsed ? (
          <span className="ml-auto shrink-0 text-[11px] text-sidebar-muted/80">
            Devoteam{version ? ` · v${shortVersion(version)}` : ""}
          </span>
        ) : null}
      </div>
    </SimpleTooltip>
  );
}

/** Desktop sidebar body: brand, context, intent groups, compact status footer. */
function SidebarContent({ collapsed }: { collapsed: boolean }) {
  const { toggleSidebar } = useShell();
  const sections = useVisibleSections();
  const activeHref = useActiveHref();
  const badges = useNavBadges();
  const toggleLabel = collapsed ? "Déplier la barre latérale" : "Replier la barre latérale";

  return (
    <div className="flex h-full flex-col">
      <div className={cn("flex shrink-0 flex-col gap-3 pb-2 pt-3.5", collapsed ? "items-center px-2" : "px-3")}>
        <Link
          href="/dashboard"
          className={cn("rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", !collapsed && "px-1")}
          aria-label="FORGE — vue d'ensemble"
        >
          {collapsed ? <ForgeMark height={26} label={null} /> : <ForgeLogo />}
        </Link>
        <ContextSwitcher collapsed={collapsed} />
      </div>

      <nav className={cn("flex-1 overflow-y-auto pb-4 pt-2", collapsed ? "px-2" : "px-3")} aria-label="Navigation principale">
        {sections.map((section) => (
          <div key={section.id} className={cn(section.heading && (collapsed ? "mt-3" : "mt-5"))}>
            {section.heading && !collapsed ? (
              <p
                className="px-2 pb-1 text-[10.5px] font-medium uppercase tracking-[0.08em] text-sidebar-muted/75"
                id={`nav-${section.id}`}
              >
                {section.label}
              </p>
            ) : null}
            {section.heading && collapsed ? <div className="mx-auto mb-2 h-px w-5 bg-sidebar-border" aria-hidden /> : null}
            <ul
              className="grid gap-px"
              aria-labelledby={section.heading && !collapsed ? `nav-${section.id}` : undefined}
              aria-label={!section.heading || collapsed ? section.label : undefined}
            >
              {section.items.map((item) => (
                <li key={item.href}>
                  <NavLink
                    item={item}
                    active={item.href === activeHref}
                    collapsed={collapsed}
                    badge={item.badge ? badges[item.badge] : undefined}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div
        className={cn(
          "flex shrink-0 items-center gap-2 border-t border-sidebar-border py-2.5",
          collapsed ? "flex-col px-2" : "px-3",
        )}
      >
        <div className={cn("min-w-0", !collapsed && "flex-1")}>
          <SystemStatus collapsed={collapsed} />
        </div>
        <SimpleTooltip content={toggleLabel} side={collapsed ? "right" : "top"}>
          <button
            type="button"
            onClick={toggleSidebar}
            className="flex size-7 shrink-0 items-center justify-center rounded-md text-sidebar-muted transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
            aria-label={toggleLabel}
            aria-expanded={!collapsed}
            aria-keyshortcuts="Meta+B Control+B"
          >
            {collapsed ? <PanelLeftOpen className="size-4" aria-hidden /> : <PanelLeftClose className="size-4" aria-hidden />}
          </button>
        </SimpleTooltip>
      </div>
    </div>
  );
}

/** Sticky desktop sidebar (≥ lg), collapsible to an icon rail. */
export function AppSidebar() {
  const { sidebarCollapsed } = useShell();
  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 border-r border-sidebar-border bg-sidebar transition-[width] duration-200 ease-out motion-reduce:transition-none lg:block",
        sidebarCollapsed ? "w-[64px]" : "w-[240px]",
      )}
    >
      <SidebarContent collapsed={sidebarCollapsed} />
    </aside>
  );
}
