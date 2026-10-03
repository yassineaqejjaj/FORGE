"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import type { Dashboard } from "@/lib/api/dashboard";
import { formatNumber } from "@/lib/format";

function Fact({ value, label, href }: { value: number; label: string; href: string }) {
  return (
    <Link
      href={href}
      className="rounded px-1 py-0.5 transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="font-semibold tabular-nums text-foreground">{formatNumber(value, 0)}</span> {label}
    </Link>
  );
}

/** Level 3: the lab's inventory in one line (agents, versions, scenarios, executions, comparisons). */
export function OverviewContext({ data }: { data: Dashboard | undefined }) {
  if (!data) return <Skeleton className="h-6 w-full max-w-xl" />;
  const { counts } = data;
  return (
    <section
      aria-label="Contexte"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground"
    >
      <Fact value={counts.agents} label={counts.agents > 1 ? "agents" : "agent"} href="/agents" />
      <span aria-hidden>·</span>
      <Fact value={counts.agent_versions} label={counts.agent_versions > 1 ? "versions" : "version"} href="/agents" />
      <span aria-hidden>·</span>
      <Fact value={counts.scenarios} label={counts.scenarios > 1 ? "scénarios" : "scénario"} href="/scenarios" />
      <span aria-hidden>·</span>
      <Fact value={counts.runs} label={counts.runs > 1 ? "exécutions" : "exécution"} href="/runs" />
      {data.comparisons_completed > 0 ? (
        <>
          <span aria-hidden>·</span>
          <Link
            href="/benchmarks"
            className="inline-flex items-center gap-1 rounded px-1 py-0.5 transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="font-semibold tabular-nums text-foreground">{data.comparisons_completed}</span>
            comparaison{data.comparisons_completed > 1 ? "s" : ""} terminée
            {data.comparisons_completed > 1 ? "s" : ""}
            <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        </>
      ) : null}
    </section>
  );
}
