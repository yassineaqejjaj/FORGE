import * as React from "react";
import { Anvil } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";

export interface ModulePlaceholderProps {
  title: string;
  description?: string;
  /** Section label above the title ("Laboratoire"). */
  eyebrow?: string;
  icon?: React.ReactNode;
  /** Planned capabilities listed in the empty state. */
  upcoming?: string[];
  /** Header actions (kept so feature owners can drop their buttons in). */
  actions?: React.ReactNode;
}

/** Temporary page body for routes whose feature module is being integrated (PageHeader + EmptyState). */
export function ModulePlaceholder({ title, description, eyebrow, icon, upcoming, actions }: ModulePlaceholderProps) {
  return (
    <>
      <PageHeader
        title={title}
        description={description}
        eyebrow={eyebrow}
        icon={icon}
        actions={actions}
        meta={
          <Badge tone="orange" dot>
            En cours d&apos;intégration
          </Badge>
        }
      />
      <EmptyState
        size="lg"
        icon={<Anvil />}
        title="Module en cours d'intégration"
        description="Cette vue est en cours de forge. Les données restent accessibles via l'API FORGE (/api/v1) et la CLI."
      >
        {upcoming?.length ? (
          <ul className="mt-2 grid max-w-md gap-1.5 text-left text-[13px] text-muted-foreground">
            {upcoming.map((item) => (
              <li key={item} className="flex items-start gap-2">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand" aria-hidden />
                {item}
              </li>
            ))}
          </ul>
        ) : null}
      </EmptyState>
    </>
  );
}
