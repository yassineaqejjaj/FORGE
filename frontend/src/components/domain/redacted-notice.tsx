import { EyeOff } from "lucide-react";

import { cn } from "@/lib/utils";

export interface RedactedNoticeProps {
  /** "inline": one-line chip in place of a value · "block": placeholder panel in place of content. */
  variant?: "inline" | "block";
  /** Main text (default "Contenu masqué (scénario privé)"). */
  title?: string;
  /** Explanation under the title (block variant). */
  description?: string | null;
  className?: string;
}

const DEFAULT_TITLE = "Contenu masqué (scénario privé)";
const DEFAULT_DESCRIPTION =
  "Les résultats restent visibles (scores, erreurs, coûts, latences) ; le contenu du scénario, les entrées / sorties de l'agent et les justifications sont réservés aux mainteneurs.";

/**
 * Placeholder rendered where the API redacted private-scenario content (docs/ARCHITECTURE.md §3.3).
 * The API decides what is redacted; the UI only displays this notice.
 */
export function RedactedNotice({ variant = "block", title = DEFAULT_TITLE, description = DEFAULT_DESCRIPTION, className }: RedactedNoticeProps) {
  if (variant === "inline") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-md border border-dashed border-violet-300 bg-violet-50/60 px-2 py-0.5 text-xs font-medium text-violet-800 dark:border-violet-400/30 dark:bg-violet-400/10 dark:text-violet-200",
          className,
        )}
      >
        <EyeOff className="size-3.5 shrink-0" aria-hidden />
        {title}
      </span>
    );
  }
  return (
    <div
      role="note"
      className={cn(
        "flex items-start gap-3 rounded-lg border border-dashed border-violet-300 bg-violet-50/50 px-4 py-3 text-[13px] text-violet-950 dark:border-violet-400/30 dark:bg-violet-400/[0.07] dark:text-violet-100",
        className,
      )}
    >
      <span className="mt-px flex size-6 shrink-0 items-center justify-center rounded-md bg-violet-600 text-white dark:bg-violet-400 dark:text-violet-950" aria-hidden>
        <EyeOff className="size-3.5" />
      </span>
      <div className="grid gap-0.5">
        <p className="font-semibold">{title}</p>
        {description ? <p className="leading-relaxed opacity-85">{description}</p> : null}
      </div>
    </div>
  );
}
