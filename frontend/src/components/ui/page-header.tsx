import * as React from "react";

import { cn } from "@/lib/utils";

export interface PageHeaderProps {
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Small label above the title (e.g. section name). */
  eyebrow?: React.ReactNode;
  /** Lucide icon element shown in a tinted chip before the title. */
  icon?: React.ReactNode;
  /** Right-aligned actions (buttons). */
  actions?: React.ReactNode;
  /** Badges/meta rendered next to the title. */
  meta?: React.ReactNode;
  className?: string;
  /** Content below the header (tabs, filters). */
  children?: React.ReactNode;
}

/**
 * Editorial page header (design system: 28px semibold title, 14px muted lead, no decoration).
 * `icon` is kept in the API for the navigation context but no longer drawn next to the title.
 */
export function PageHeader({ title, description, eyebrow, actions, meta, className, children }: PageHeaderProps) {
  return (
    <header className={cn("flex flex-col gap-4 pb-6", className)}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="grid min-w-0 gap-1">
            {eyebrow ? (
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-subtle-foreground">{eyebrow}</p>
            ) : null}
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <h1 className="truncate text-[24px] font-semibold leading-tight tracking-tight text-foreground sm:text-[28px]">{title}</h1>
              {meta}
            </div>
            {description ? (
              <p className="mt-0.5 max-w-3xl text-sm leading-relaxed text-muted-foreground text-balance">{description}</p>
            ) : null}
          </div>
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </header>
  );
}
