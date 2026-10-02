"use client";

import * as React from "react";
import { Search, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { SimpleSelect, type SimpleSelectOption } from "@/components/ui/select";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { cn } from "@/lib/utils";

const ALL = "__all__";

export interface FilterSelectProps {
  value: string;
  onValueChange: (value: string) => void;
  options: ReadonlyArray<SimpleSelectOption>;
  /** Label of the "no filter" option ("Toutes les catégories"). */
  allLabel: string;
  "aria-label": string;
  className?: string;
  /** Hide the "all" entry (filters that always have a value). */
  noAll?: boolean;
}

/** Select used in filter bars; "" means no filter. */
export function FilterSelect({ value, onValueChange, options, allLabel, className, noAll, ...aria }: FilterSelectProps) {
  const all: SimpleSelectOption[] = noAll ? [] : [{ value: ALL, label: allLabel }];
  return (
    <SimpleSelect
      size="sm"
      value={value || (noAll ? undefined : ALL)}
      onValueChange={(v) => onValueChange(v === ALL ? "" : v)}
      options={[...all, ...options]}
      className={cn("w-full sm:w-44", className)}
      aria-label={aria["aria-label"]}
    />
  );
}

export interface SearchInputProps {
  /** Committed value (from the URL). */
  value: string;
  /** Called (debounced) with the new search text. */
  onCommit: (value: string) => void;
  placeholder?: string;
  className?: string;
  "aria-label"?: string;
}

/** Debounced search box synced with an external (URL) value. */
export function SearchInput({ value, onCommit, placeholder = "Rechercher…", className, ...aria }: SearchInputProps) {
  const [draft, setDraft] = React.useState(value);
  const debounced = useDebouncedValue(draft, 300);
  const lastCommitted = React.useRef(value);

  React.useEffect(() => {
    if (value !== lastCommitted.current) {
      lastCommitted.current = value;
      setDraft(value);
    }
  }, [value]);

  React.useEffect(() => {
    const trimmed = debounced.trim();
    if (trimmed !== lastCommitted.current) {
      lastCommitted.current = trimmed;
      onCommit(trimmed);
    }
  }, [debounced, onCommit]);

  return (
    <Input
      size="sm"
      type="search"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      placeholder={placeholder}
      leftIcon={<Search aria-hidden />}
      aria-label={aria["aria-label"] ?? placeholder}
      className={cn("w-full sm:w-64", className)}
      rightSlot={
        draft ? (
          <button
            type="button"
            onClick={() => setDraft("")}
            className="rounded p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Effacer la recherche"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        ) : undefined
      }
    />
  );
}

/** Wrapper row for filter controls (one line above the table, wraps on mobile). */
export function FilterBar({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center", className)}>{children}</div>;
}
