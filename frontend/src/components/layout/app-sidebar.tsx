"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { ConstellationDots, ForgeLogo, ForgeMark } from "@/components/brand/forge-logo";
import { isActiveHref, NAV_SECTIONS, type NavItem } from "@/components/layout/nav";
import { useShell } from "@/components/layout/shell-context";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useCurrentUser } from "@/hooks/use-current-user";
import { http, isApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";

function NavLink({
  item,
  active,
  collapsed,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const Icon = item.icon;
  const link = (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? item.label : undefined}
      className={cn(
        "group relative flex h-8 items-center gap-2.5 rounded-md text-[13px] font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        collapsed ? "justify-center px-0" : "px-2.5",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-sidebar-foreground hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground",
      )}
    >
      {active ? <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-brand" aria-hidden /> : null}
      <Icon
        className={cn("size-4 shrink-0", active ? "text-brand" : "text-sidebar-muted group-hover:text-sidebar-foreground")}
        aria-hidden
      />
      {!collapsed ? <span className="truncate">{item.label}</span> : null}
    </Link>
  );
  if (!collapsed) return link;
  return (
    <SimpleTooltip content={item.label} side="right">
      {link}
    </SimpleTooltip>
  );
}

/**
 * API reachability indicator. `/meta` is only read for its optional `version` string: its full
 * payload is typed by the generated OpenAPI schema and consumed by the feature pages.
 */
function SystemStatus({ collapsed }: { collapsed: boolean }) {
  const meta = useQuery({
    queryKey: queryKeys.meta(),
    queryFn: ({ signal }) => http.get<Record<string, unknown>>("/meta", { signal }),
    staleTime: 5 * 60_000,
    retry: false,
  });
  // Any HTTP answer below 500 proves the API is up (a stub router answers 501).
  const reachable =
    meta.isSuccess ||
    (meta.isError && isApiError(meta.error) && meta.error.status > 0 && (meta.error.status < 500 || meta.error.isNotImplemented));
  const version = meta.isSuccess && typeof meta.data?.version === "string" ? meta.data.version : null;
  const label = meta.isPending ? "Connexion…" : reachable ? "Plateforme opérationnelle" : "API injoignable";
  const detail = reachable
    ? `API FORGE joignable${version ? ` · version ${version}` : ""}`
    : meta.isError
      ? "Le backend FORGE ne répond pas."
      : undefined;
  const dot = (
    <span className="relative flex size-2" aria-hidden>
      {reachable ? <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-40" /> : null}
      <span
        className={cn("relative inline-flex size-2 rounded-full", meta.isPending ? "bg-stone-400" : reachable ? "bg-emerald-500" : "bg-red-500")}
      />
    </span>
  );
  return (
    <SimpleTooltip content={detail ?? label} side={collapsed ? "right" : "top"} align="start">
      <div
        className={cn("flex items-center gap-2 text-[11.5px] text-sidebar-muted", collapsed && "justify-center")}
        tabIndex={0}
        role="status"
        aria-label={detail ?? label}
      >
        {dot}
        {!collapsed ? <span className="truncate">{label}</span> : null}
        {!collapsed && version ? <span className="ml-auto font-mono text-[10.5px]">v{version}</span> : null}
      </div>
    </SimpleTooltip>
  );
}

export interface SidebarContentProps {
  /** Icon-rail mode (desktop only). */
  collapsed?: boolean;
  /** Called after a navigation (closes the mobile sheet). */
  onNavigate?: () => void;
  /** Show the collapse toggle (desktop). */
  showCollapseToggle?: boolean;
}

/** Sidebar body (used by the desktop aside and the mobile sheet). */
export function SidebarContent({ collapsed = false, onNavigate, showCollapseToggle = false }: SidebarContentProps) {
  const pathname = usePathname();
  const { hasRole } = useCurrentUser();
  const { toggleSidebar } = useShell();

  const sections = NAV_SECTIONS.map((s) => ({ ...s, items: s.items.filter((i) => !i.minRole || hasRole(i.minRole)) })).filter(
    (s) => s.items.length > 0,
  );
  // Longest matching href wins (so "/" is only active on the dashboard).
  const activeHref = sections
    .flatMap((s) => s.items)
    .filter((i) => isActiveHref(pathname, i.href))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;

  return (
    <div className="flex h-full flex-col">
      <div className={cn("flex h-14 shrink-0 items-center", collapsed ? "justify-center px-2" : "px-4")}>
        <Link
          href="/dashboard"
          onClick={onNavigate}
          className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="FORGE — tableau de bord"
        >
          {collapsed ? <ForgeMark width={28} height={28} /> : <ForgeLogo />}
        </Link>
      </div>

      <nav className={cn("flex-1 overflow-y-auto pb-4", collapsed ? "px-2" : "px-3")} aria-label="Navigation principale">
        {sections.map((section, index) => (
          <div key={section.id} className={cn(index > 0 && (collapsed ? "mt-2 border-t border-sidebar-border pt-2" : "mt-4"))}>
            {!collapsed ? (
              <p
                className="px-2.5 pb-1.5 pt-1 text-[10.5px] font-semibold uppercase tracking-[0.09em] text-sidebar-muted"
                id={`nav-${section.id}`}
              >
                {section.label}
              </p>
            ) : null}
            <ul className="grid gap-0.5" aria-labelledby={!collapsed ? `nav-${section.id}` : undefined} aria-label={collapsed ? section.label : undefined}>
              {section.items.map((item) => (
                <li key={item.href}>
                  <NavLink item={item} active={item.href === activeHref} collapsed={collapsed} onNavigate={onNavigate} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className={cn("grid shrink-0 gap-2.5 border-t border-sidebar-border py-3", collapsed ? "justify-items-center px-2" : "px-4")}>
        <SystemStatus collapsed={collapsed} />
        {!collapsed ? (
          <div className="flex items-center gap-2 text-[10.5px] text-sidebar-muted">
            <ConstellationDots />
            <span>Programme NOVA · Devoteam</span>
          </div>
        ) : null}
        {showCollapseToggle ? (
          <SimpleTooltip content={collapsed ? "Déplier la barre latérale" : "Replier la barre latérale"} side={collapsed ? "right" : "top"}>
            <button
              type="button"
              onClick={toggleSidebar}
              className={cn(
                "flex h-7 items-center gap-2 rounded-md text-[12px] text-sidebar-muted transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                collapsed ? "w-8 justify-center" : "px-2",
              )}
              aria-label={collapsed ? "Déplier la barre latérale" : "Replier la barre latérale"}
              aria-expanded={!collapsed}
              aria-keyshortcuts="Meta+B Control+B"
            >
              {collapsed ? <PanelLeftOpen className="size-4" aria-hidden /> : <PanelLeftClose className="size-4" aria-hidden />}
              {!collapsed ? <span>Replier</span> : null}
            </button>
          </SimpleTooltip>
        ) : null}
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
        "sticky top-0 hidden h-dvh shrink-0 border-r border-sidebar-border bg-sidebar transition-[width] duration-200 ease-out lg:block",
        sidebarCollapsed ? "w-[64px]" : "w-[248px]",
      )}
    >
      <SidebarContent collapsed={sidebarCollapsed} showCollapseToggle />
    </aside>
  );
}
