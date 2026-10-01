"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";

import { activeNav, activeSettingsNav } from "@/components/layout/nav";
import { useShell } from "@/components/layout/shell-context";
import { shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Crumb {
  label: string;
  href?: string;
}

function safeDecode(v: string): string {
  try {
    return decodeURIComponent(v);
  } catch {
    return v;
  }
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Header breadcrumb derived from the route: {section} / {page} / {élément}. */
export function Breadcrumbs({ className }: { className?: string }) {
  const pathname = usePathname();
  const { crumbLabels } = useShell();
  const match = activeNav(pathname);

  const crumbs: Crumb[] = [];
  if (match) {
    crumbs.push({ label: match.section.label });
    crumbs.push({ label: match.item.label, href: match.item.href });
    const settings = activeSettingsNav(pathname);
    if (settings) crumbs.push({ label: settings.label, href: settings.href });
    const base = settings?.href ?? match.item.href;
    const rest = pathname
      .slice(base === "/" ? 1 : base.length)
      .split("/")
      .filter(Boolean)
      .map(safeDecode);
    let href = base === "/" ? "" : base;
    rest.forEach((segment, i) => {
      href = `${href}/${encodeURIComponent(segment)}`;
      const custom = crumbLabels[segment];
      const label =
        custom ??
        (UUID_RE.test(segment) && i === 0 && match.item.entity
          ? `${match.item.entity} ${shortId(segment)}`
          : UUID_RE.test(segment)
            ? shortId(segment)
            : segment);
      crumbs.push({ label, href });
    });
  } else {
    crumbs.push({ label: "FORGE", href: "/" });
  }

  return (
    <nav aria-label="Fil d'Ariane" className={cn("min-w-0", className)}>
      <ol className="flex min-w-0 items-center gap-1 text-[13px]">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <li
              key={`${c.label}-${i}`}
              className={cn(
                "flex min-w-0 items-center gap-1",
                !last && "hidden sm:flex",
                !last && i < crumbs.length - 2 && "sm:hidden md:flex",
              )}
            >
              {c.href && !last ? (
                <Link
                  href={c.href}
                  className="truncate rounded px-1 py-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {c.label}
                </Link>
              ) : (
                <span
                  className={cn("truncate px-1", last ? "font-medium text-foreground" : "text-subtle-foreground")}
                  aria-current={last ? "page" : undefined}
                >
                  {c.label}
                </span>
              )}
              {!last ? <ChevronRight className="size-3.5 shrink-0 text-subtle-foreground" aria-hidden /> : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
