"use client";

import * as React from "react";
import { ChevronDown, FilterX, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { cn } from "@/lib/utils";

const ALL = "__all__";

export interface FilterOption {
  value: string;
  label: React.ReactNode;
  description?: React.ReactNode;
}

/** Labelled filter cell (label above the control, dense). */
export function FilterField({ label, htmlFor, className, children }: { label: string; htmlFor?: string; className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("grid min-w-0 gap-1", className)}>
      <Label htmlFor={htmlFor} className="text-[11.5px] font-medium text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}

export interface FilterSelectProps {
  id: string;
  label: string;
  value: string | undefined;
  onChange: (value: string | undefined) => void;
  options: ReadonlyArray<FilterOption>;
  allLabel?: string;
  disabled?: boolean;
  className?: string;
  loading?: boolean;
}

/** Single-choice filter; the first entry ("Tous") clears it. */
export function FilterSelect({ id, label, value, onChange, options, allLabel = "Tous", disabled, className, loading }: FilterSelectProps) {
  const known = !value || options.some((o) => o.value === value);
  return (
    <FilterField label={label} htmlFor={id} className={className}>
      <Select value={value ?? ALL} onValueChange={(v) => onChange(v === ALL ? undefined : v)} disabled={disabled}>
        <SelectTrigger id={id} size="sm" aria-label={label}>
          <SelectValue placeholder={allLabel} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>{allLabel}</SelectItem>
          {options.length || !known ? <SelectSeparator /> : null}
          {!known && value ? <SelectItem value={value}>{loading ? "Chargement…" : `Sélection (${value.slice(0, 8)})`}</SelectItem> : null}
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value} description={o.description}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FilterField>
  );
}

export interface MultiFilterProps {
  id: string;
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  options: ReadonlyArray<FilterOption & { label: string }>;
  allLabel?: string;
  className?: string;
}

/** Multi-choice filter in a dropdown (checkbox items). */
export function MultiFilter({ id, label, values, onChange, options, allLabel = "Tous", className }: MultiFilterProps) {
  const selected = new Set(values);
  const summary =
    values.length === 0
      ? allLabel
      : values.length === 1
        ? (options.find((o) => o.value === values[0])?.label ?? values[0])
        : `${values.length} sélectionnés`;
  return (
    <FilterField label={label} htmlFor={id} className={className}>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            id={id}
            type="button"
            className={cn(
              "flex h-8 w-full min-w-0 items-center justify-between gap-2 rounded-lg border border-input bg-surface-2 px-3 text-left text-[13px]",
              "focus-visible:border-ring/60 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/40",
              values.length === 0 && "text-subtle-foreground",
            )}
            aria-label={`${label} : ${summary}`}
          >
            <span className="truncate">{summary}</span>
            <ChevronDown className="size-4 shrink-0 text-subtle-foreground" aria-hidden />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="max-h-80 min-w-[14rem]">
          <DropdownMenuLabel>{label}</DropdownMenuLabel>
          {options.map((o) => (
            <DropdownMenuCheckboxItem
              key={o.value}
              checked={selected.has(o.value)}
              onSelect={(e) => e.preventDefault()}
              onCheckedChange={(checked) => {
                const next = new Set(selected);
                if (checked) next.add(o.value);
                else next.delete(o.value);
                onChange(options.map((x) => x.value).filter((v) => next.has(v)));
              }}
            >
              {o.label}
            </DropdownMenuCheckboxItem>
          ))}
          {values.length ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => onChange([])}>Effacer la sélection</DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    </FilterField>
  );
}

/** Search box that commits its value after a short debounce. */
export function SearchFilter({
  id,
  label,
  value,
  onChange,
  placeholder,
  className,
}: {
  id: string;
  label: string;
  value: string | undefined;
  onChange: (value: string | undefined) => void;
  placeholder?: string;
  className?: string;
}) {
  const [text, setText] = React.useState(value ?? "");
  const debounced = useDebouncedValue(text, 350);
  const onChangeRef = React.useRef(onChange);
  React.useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);
  React.useEffect(() => {
    setText(value ?? "");
  }, [value]);
  React.useEffect(() => {
    const next = debounced.trim() || undefined;
    if (next !== (value || undefined)) onChangeRef.current(next);
    // `value` intentionally omitted: only user typing commits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);
  return (
    <FilterField label={label} htmlFor={id} className={className}>
      <Input
        id={id}
        size="sm"
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        leftIcon={<Search aria-hidden />}
      />
    </FilterField>
  );
}

/** Numeric input committing on blur / Enter. */
export function NumberFilter({
  id,
  label,
  value,
  onChange,
  min,
  max,
  step,
  placeholder,
  className,
}: {
  id: string;
  label: string;
  value: number | undefined;
  onChange: (value: number | undefined) => void;
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
  className?: string;
}) {
  const [text, setText] = React.useState(value === undefined ? "" : String(value));
  React.useEffect(() => setText(value === undefined ? "" : String(value)), [value]);
  const commit = () => {
    const trimmed = text.trim().replace(",", ".");
    if (!trimmed) return onChange(undefined);
    const n = Number(trimmed);
    if (!Number.isFinite(n)) return setText(value === undefined ? "" : String(value));
    const clamped = Math.min(max ?? n, Math.max(min ?? n, n));
    if (clamped !== value) onChange(clamped);
    setText(String(clamped));
  };
  return (
    <FilterField label={label} htmlFor={id} className={className}>
      <Input
        id={id}
        size="sm"
        inputMode="decimal"
        value={text}
        min={min}
        max={max}
        step={step}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
      />
    </FilterField>
  );
}

/** Native date input ("AAAA-MM-JJ"). */
export function DateFilter({
  id,
  label,
  value,
  onChange,
  className,
}: {
  id: string;
  label: string;
  value: string | undefined;
  onChange: (value: string | undefined) => void;
  className?: string;
}) {
  return (
    <FilterField label={label} htmlFor={id} className={className}>
      <Input id={id} size="sm" type="date" value={value ?? ""} onChange={(e) => onChange(e.target.value || undefined)} />
    </FilterField>
  );
}

/** Filter panel container with a reset button. */
export function FilterBar({
  children,
  activeCount,
  onReset,
  className,
  label = "Filtres",
}: {
  children: React.ReactNode;
  activeCount: number;
  onReset: () => void;
  className?: string;
  label?: string;
}) {
  return (
    <section aria-label={label} className={cn("rounded-xl border border-border bg-card p-3 shadow-panel sm:p-4", className)}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">{children}</div>
      {activeCount > 0 ? (
        <div className="mt-3 flex items-center justify-between gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
          <span>
            {activeCount} filtre{activeCount > 1 ? "s" : ""} actif{activeCount > 1 ? "s" : ""}
          </span>
          <Button variant="ghost" size="xs" onClick={onReset} leftIcon={<FilterX aria-hidden />}>
            Réinitialiser
          </Button>
        </div>
      ) : null}
    </section>
  );
}
