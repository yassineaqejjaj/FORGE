import * as React from "react";

import { cn } from "@/lib/utils";

export interface DetailItem {
  label: React.ReactNode;
  value: React.ReactNode;
  /** Span the full width of the grid. */
  full?: boolean;
}

/** Key / value grid (description list) for metadata panels. */
export function DetailList({
  items,
  columns = 2,
  className,
}: {
  items: ReadonlyArray<DetailItem | null | false | undefined>;
  columns?: 1 | 2 | 3;
  className?: string;
}) {
  return (
    <dl
      className={cn(
        "grid gap-x-6 gap-y-3.5",
        columns === 2 && "sm:grid-cols-2",
        columns === 3 && "sm:grid-cols-2 lg:grid-cols-3",
        className,
      )}
    >
      {items.filter(Boolean).map((item, i) => {
        const it = item as DetailItem;
        return (
          <div key={i} className={cn("grid min-w-0 content-start gap-1", it.full && "sm:col-span-full")}>
            <dt className="text-[11.5px] font-medium uppercase tracking-wide text-subtle-foreground">{it.label}</dt>
            <dd className="min-w-0 break-words text-[13px] text-foreground">{it.value}</dd>
          </div>
        );
      })}
    </dl>
  );
}

/** Muted em-dash placeholder for missing values. */
export function Empty({ children = "—" }: { children?: React.ReactNode }) {
  return <span className="text-subtle-foreground">{children}</span>;
}
