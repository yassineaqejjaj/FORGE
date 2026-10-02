"use client";

import * as React from "react";
import { X } from "lucide-react";

import { inputBaseClasses } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface TagInputProps {
  id: string;
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  invalid?: boolean;
  /** Maximum number of items. */
  max?: number;
  className?: string;
  "aria-describedby"?: string;
}

/** Free-text list editor: Entrée or « , » adds an item, Retour arrière removes the last one. */
export function TagInput({
  id,
  value,
  onChange,
  placeholder = "Ajouter puis Entrée",
  disabled,
  invalid,
  max = 50,
  className,
  ...aria
}: TagInputProps) {
  const [draft, setDraft] = React.useState("");

  const commit = (raw: string) => {
    const parts = raw
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean);
    if (!parts.length) return;
    const next = [...value];
    for (const p of parts) if (!next.includes(p) && next.length < max) next.push(p);
    onChange(next);
    setDraft("");
  };

  return (
    <div
      className={cn(
        inputBaseClasses,
        "flex min-h-9 flex-wrap items-center gap-1.5 px-2 py-1.5 focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/20",
        invalid && "border-destructive",
        disabled && "opacity-60",
        className,
      )}
    >
      {value.map((tag) => (
        <span
          key={tag}
          className="inline-flex h-6 items-center gap-1 rounded-md bg-muted px-2 text-xs font-medium text-foreground"
        >
          {tag}
          {!disabled ? (
            <button
              type="button"
              onClick={() => onChange(value.filter((t) => t !== tag))}
              className="rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={`Retirer ${tag}`}
            >
              <X className="size-3" aria-hidden />
            </button>
          ) : null}
        </span>
      ))}
      <input
        id={id}
        value={draft}
        disabled={disabled}
        onChange={(e) => {
          const v = e.target.value;
          if (v.includes(",")) commit(v);
          else setDraft(v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit(draft);
          } else if (e.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => commit(draft)}
        placeholder={value.length ? "" : placeholder}
        className="min-w-24 flex-1 bg-transparent text-sm outline-none placeholder:text-subtle-foreground"
        aria-invalid={invalid || undefined}
        {...aria}
      />
    </div>
  );
}
