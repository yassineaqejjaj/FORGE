"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Bot, Boxes, ChevronsUpDown, Layers3 } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { http } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useAgentOptions } from "@/lib/api/runs";
import { cn } from "@/lib/utils";

/**
 * Active context of the workspace (« système évalué »).
 *
 * FORGE has no multi-project model yet: the context is the agent the user is working on, chosen
 * among the registered agents, plus the deployment environment reported by `/meta`. Choosing an
 * agent opens it; the choice is remembered per browser and follows the agent pages. The component
 * is the future entry point for projects, environments and teams.
 */

const STORAGE_KEY = "forge-context-agent";
const ALL = "__all__";
const AGENT_ROUTE = /^\/agents\/([0-9a-f-]{36})(?:\/|$)/i;

const ENVIRONMENT_LABELS: Record<string, { label: string; tone: string }> = {
  production: { label: "Production", tone: "bg-emerald-500" },
  development: { label: "Développement", tone: "bg-amber-500" },
  test: { label: "Test", tone: "bg-sky-500" },
};

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function store(value: string | null) {
  try {
    if (value) window.localStorage.setItem(STORAGE_KEY, value);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // storage unavailable: the context only lives for this page
  }
}

function useEnvironment() {
  const meta = useQuery({
    queryKey: queryKeys.meta(),
    queryFn: ({ signal }) => http.get<Record<string, unknown>>("/meta", { signal }),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const env = typeof meta.data?.environment === "string" ? meta.data.environment : null;
  return env ? (ENVIRONMENT_LABELS[env] ?? { label: env, tone: "bg-stone-400" }) : null;
}

export function ContextSwitcher({ collapsed = false, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const agents = useAgentOptions();
  const environment = useEnvironment();
  const [selected, setSelected] = React.useState<string | null>(null);

  React.useEffect(() => {
    setSelected(readStored());
  }, []);

  // The agent being viewed becomes the context.
  const routeAgent = AGENT_ROUTE.exec(pathname)?.[1] ?? null;
  React.useEffect(() => {
    if (routeAgent) {
      setSelected(routeAgent);
      store(routeAgent);
    }
  }, [routeAgent]);

  const items = (agents.data?.items ?? []).filter((a) => !a.archived);
  const current = selected ? items.find((a) => a.id === selected) : undefined;
  const title = current?.name ?? "Tous les systèmes";
  const subtitle = environment?.label ?? (agents.isPending ? "Chargement…" : "Environnement");
  const label = `Contexte : ${title} · ${subtitle}. Changer de système évalué`;

  const choose = (value: string) => {
    const next = value === ALL ? null : value;
    setSelected(next);
    store(next);
    onNavigate?.();
    router.push(next ? `/agents/${next}` : "/agents");
  };

  const trigger = collapsed ? (
    <button
      type="button"
      aria-label={label}
      className="flex size-9 items-center justify-center rounded-md border border-sidebar-border bg-background text-sidebar-foreground transition-colors hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Boxes className="size-4" aria-hidden />
    </button>
  ) : (
    <button
      type="button"
      aria-label={label}
      className={cn(
        "group flex w-full min-w-0 items-center gap-2.5 rounded-lg border border-sidebar-border bg-background px-2.5 py-2 text-left shadow-xs transition-colors",
        "hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:border-border-strong",
      )}
    >
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-brand-soft text-brand" aria-hidden>
        {current ? <Bot className="size-4" /> : <Layers3 className="size-4" />}
      </span>
      <span className="grid min-w-0 flex-1 leading-tight">
        <span className="truncate text-[13px] font-semibold text-sidebar-accent-foreground">{title}</span>
        <span className="flex items-center gap-1.5 truncate text-[11.5px] text-sidebar-muted">
          {environment ? <span className={cn("size-1.5 shrink-0 rounded-full", environment.tone)} aria-hidden /> : null}
          {subtitle}
        </span>
      </span>
      <ChevronsUpDown className="size-3.5 shrink-0 text-sidebar-muted group-hover:text-sidebar-foreground" aria-hidden />
    </button>
  );

  return (
    <DropdownMenu>
      {collapsed ? (
        <SimpleTooltip content={`${title} · ${subtitle}`} side="right">
          <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
        </SimpleTooltip>
      ) : (
        <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      )}
      <DropdownMenuContent align="start" side={collapsed ? "right" : "bottom"} className="w-64">
        <DropdownMenuLabel className="text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle-foreground">
          Système évalué
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup value={current?.id ?? ALL} onValueChange={choose}>
          <DropdownMenuRadioItem value={ALL}>Tous les systèmes</DropdownMenuRadioItem>
          {items.slice(0, 12).map((agent) => (
            <DropdownMenuRadioItem key={agent.id} value={agent.id}>
              <span className="truncate">{agent.name}</span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {items.length > 12 ? (
          <DropdownMenuItem onSelect={() => choose(ALL)} className="text-muted-foreground">
            Voir les {items.length} agents…
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled className="flex-col items-start gap-0.5">
          <span>Projets, environnements et équipes</span>
          <span className="text-[11px] text-subtle-foreground">Bientôt disponible</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
