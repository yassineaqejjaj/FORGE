"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import { ArrowRight, Hash, LogOut, Moon, PanelLeft, Search, Sun } from "lucide-react";

import { NAV_SECTIONS, SETTINGS_NAV, type NavItem } from "@/components/layout/nav";
import { useShell } from "@/components/layout/shell-context";
import { useTheme } from "@/components/providers/theme-provider";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useHotkey } from "@/hooks/use-hotkey";
import { useLogout } from "@/lib/api/auth";
import { shortId } from "@/lib/format";
import { cn, normalizeText } from "@/lib/utils";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Entities that can be opened directly from a pasted identifier. */
const OPEN_BY_ID: Array<{ label: string; href: (id: string) => string }> = [
  { label: "Ouvrir le run", href: (id) => `/runs/${id}` },
  { label: "Ouvrir l'expérience", href: (id) => `/experiments/${id}` },
  { label: "Ouvrir le benchmark", href: (id) => `/benchmarks/${id}` },
  { label: "Ouvrir le scénario", href: (id) => `/scenarios/${id}` },
  { label: "Ouvrir l'agent", href: (id) => `/agents/${id}` },
];

function matches(query: string, ...fields: Array<string | undefined>): boolean {
  const q = normalizeText(query);
  if (!q) return true;
  return fields.some((f) => f && normalizeText(f).includes(q));
}

function itemMatches(query: string, item: NavItem): boolean {
  return matches(query, item.label, item.description, ...(item.keywords ?? []));
}

const itemClass = cn(
  "group flex cursor-default select-none items-center gap-3 rounded-md px-2.5 py-2 text-[13px] text-foreground outline-none",
  "data-[selected=true]:bg-accent data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50",
  "[&_svg]:size-4 [&_svg]:shrink-0",
);

const groupClass = cn(
  "px-1.5 pb-1 [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:pt-3",
  "[&_[cmdk-group-heading]]:text-[10.5px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase",
  "[&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-subtle-foreground",
);

/** Global ⌘K / Ctrl+K palette: navigation (filtered by role), open by identifier, actions. */
export function CommandPalette() {
  const router = useRouter();
  const { commandPaletteOpen: open, setCommandPaletteOpen: setOpen, toggleSidebar, sidebarCollapsed } = useShell();
  const { resolvedTheme, setTheme } = useTheme();
  const { hasRole } = useCurrentUser();
  const logout = useLogout();
  const [query, setQuery] = React.useState("");

  useHotkey("k", () => setOpen(!open), { mod: true });
  useHotkey("/", () => setOpen(true), { enabled: !open });
  useHotkey("b", () => toggleSidebar(), { mod: true, allowInInputs: false });

  React.useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const run = React.useCallback(
    (fn: () => void) => {
      setOpen(false);
      // Let the dialog close before navigating (focus restoration).
      window.setTimeout(fn, 0);
    },
    [setOpen],
  );

  const allowed = (item: NavItem) => !item.minRole || hasRole(item.minRole);
  const sections = NAV_SECTIONS.map((s) => ({
    ...s,
    items: s.items.filter((i) => allowed(i) && itemMatches(query, i)),
  })).filter((s) => s.items.length > 0);
  const settingsItems = SETTINGS_NAV.filter((i) => allowed(i) && itemMatches(query, i));

  const trimmed = query.trim();
  const idCandidate = UUID_RE.test(trimmed) ? trimmed.toLowerCase() : null;

  const actions = [
    {
      id: "theme",
      label: resolvedTheme === "dark" ? "Passer au thème clair" : "Passer au thème sombre",
      icon: resolvedTheme === "dark" ? Sun : Moon,
      keywords: "thème apparence clair sombre dark light",
      run: () => setTheme(resolvedTheme === "dark" ? "light" : "dark"),
    },
    {
      id: "sidebar",
      label: sidebarCollapsed ? "Déplier la barre latérale" : "Replier la barre latérale",
      icon: PanelLeft,
      keywords: "sidebar menu navigation replier déplier",
      run: () => toggleSidebar(),
    },
    { id: "logout", label: "Se déconnecter", icon: LogOut, keywords: "déconnexion logout", run: () => logout.mutate() },
  ].filter((a) => matches(query, a.label, a.keywords));

  const nothing = sections.length === 0 && settingsItems.length === 0 && actions.length === 0 && !idCandidate;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        hideClose
        size="lg"
        className="top-[12vh] translate-y-0 gap-0 overflow-hidden p-0 sm:top-[14vh]"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <DialogTitle className="sr-only">Navigation et commandes</DialogTitle>
        <DialogDescription className="sr-only">
          Allez à une page de FORGE, ouvrez un élément par son identifiant ou lancez une action.
        </DialogDescription>
        <Command shouldFilter={false} loop label="Navigation et commandes" className="flex max-h-[min(70vh,560px)] flex-col">
          <div className="flex items-center gap-2.5 border-b border-border px-4">
            <Search className="size-4 shrink-0 text-subtle-foreground" aria-hidden />
            <Command.Input
              autoFocus
              value={query}
              onValueChange={setQuery}
              placeholder="Aller à une page, coller un identifiant, lancer une action…"
              className="h-12 w-full min-w-0 bg-transparent text-sm text-foreground outline-none placeholder:text-subtle-foreground"
            />
            <Kbd className="hidden sm:inline-flex">Échap</Kbd>
          </div>

          <Command.List className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1">
            {idCandidate ? (
              <Command.Group heading={`Identifiant ${shortId(idCandidate)}`} className={groupClass}>
                {OPEN_BY_ID.map((target) => (
                  <Command.Item
                    key={target.label}
                    value={`id-${target.label}`}
                    onSelect={() => run(() => router.push(target.href(idCandidate)))}
                    className={itemClass}
                  >
                    <Hash className="text-muted-foreground" aria-hidden />
                    <span>{target.label}</span>
                    <span className="truncate font-mono text-[11px] text-subtle-foreground">{shortId(idCandidate)}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            ) : null}

            {sections.map((section) => (
              <Command.Group key={section.id} heading={section.label} className={groupClass}>
                {section.items.map((item) => (
                  <Command.Item
                    key={item.href}
                    value={`nav-${item.href}`}
                    onSelect={() => run(() => router.push(item.href))}
                    className={itemClass}
                  >
                    <item.icon className="text-muted-foreground" aria-hidden />
                    <span className="font-medium">{item.label}</span>
                    <span className="hidden truncate text-xs text-muted-foreground sm:inline">{item.description}</span>
                    <ArrowRight className="ml-auto opacity-0 group-data-[selected=true]:opacity-60" aria-hidden />
                  </Command.Item>
                ))}
              </Command.Group>
            ))}

            {settingsItems.length > 0 ? (
              <Command.Group heading="Paramètres" className={groupClass}>
                {settingsItems.map((item) => (
                  <Command.Item
                    key={item.href}
                    value={`nav-${item.href}`}
                    onSelect={() => run(() => router.push(item.href))}
                    className={itemClass}
                  >
                    <item.icon className="text-muted-foreground" aria-hidden />
                    <span className="font-medium">{item.label}</span>
                    <span className="hidden truncate text-xs text-muted-foreground sm:inline">{item.description}</span>
                    <ArrowRight className="ml-auto opacity-0 group-data-[selected=true]:opacity-60" aria-hidden />
                  </Command.Item>
                ))}
              </Command.Group>
            ) : null}

            {actions.length > 0 ? (
              <Command.Group heading="Actions" className={groupClass}>
                {actions.map((a) => (
                  <Command.Item key={a.id} value={`action-${a.id}`} onSelect={() => run(a.run)} className={itemClass}>
                    <a.icon className="text-muted-foreground" aria-hidden />
                    <span>{a.label}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            ) : null}

            {nothing ? (
              <div className="px-4 py-10 text-center text-sm text-muted-foreground">Aucun résultat pour « {trimmed} ».</div>
            ) : null}
          </Command.List>

          <div className="flex items-center justify-between gap-3 border-t border-border bg-muted/40 px-4 py-2 text-[11px] text-subtle-foreground">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1">
                <Kbd>↑</Kbd>
                <Kbd>↓</Kbd> naviguer
              </span>
              <span className="flex items-center gap-1">
                <Kbd>↵</Kbd> ouvrir
              </span>
            </div>
            <span className="hidden sm:inline">Collez un identifiant (UUID) pour ouvrir un run, une expérience…</span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
