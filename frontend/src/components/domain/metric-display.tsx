import { SimpleTooltip } from "@/components/ui/tooltip";
import { formatCost, formatMs, formatNumber, formatTokens, type Currency } from "@/lib/format";
import { cn } from "@/lib/utils";

interface BaseProps {
  className?: string;
  /** Muted styling (secondary columns). */
  muted?: boolean;
}

export interface CostDisplayProps extends BaseProps {
  /** Amount (numbers or Decimal strings from the API). */
  value: number | string | null | undefined;
  currency?: Currency | string;
  /** Suffix such as "/ run". */
  suffix?: string;
}

/** Cost with adaptive precision ("0,0042 €", "12,40 $"); the exact amount is in the tooltip. */
export function CostDisplay({ value, currency = "EUR", suffix, className, muted }: CostDisplayProps) {
  const n = typeof value === "string" ? Number(value) : value;
  if (typeof n !== "number" || !Number.isFinite(n)) {
    return (
      <span className={cn("text-subtle-foreground", className)} title="Coût non disponible">
        —
      </span>
    );
  }
  return (
    <SimpleTooltip content={`${formatNumber(n, 8)} ${String(currency).toUpperCase()}`}>
      <span className={cn("whitespace-nowrap tabular-nums", muted && "text-muted-foreground", className)}>
        {formatCost(n, currency)}
        {suffix ? <span className="ml-0.5 text-muted-foreground">{suffix}</span> : null}
      </span>
    </SimpleTooltip>
  );
}

export interface DurationDisplayProps extends BaseProps {
  /** Duration in milliseconds. */
  ms: number | null | undefined;
}

/** Duration: "842 ms", "1,2 s", "2 min 03 s" (exact milliseconds in the tooltip). */
export function DurationDisplay({ ms, className, muted }: DurationDisplayProps) {
  if (typeof ms !== "number" || !Number.isFinite(ms)) {
    return (
      <span className={cn("text-subtle-foreground", className)} title="Durée non disponible">
        —
      </span>
    );
  }
  return (
    <span
      className={cn("whitespace-nowrap tabular-nums", muted && "text-muted-foreground", className)}
      title={`${formatNumber(ms, 0)} ms`}
    >
      {formatMs(ms)}
    </span>
  );
}

export interface TokenCountProps extends BaseProps {
  /** Total tokens (defaults to input + output when omitted). */
  total?: number | null;
  input?: number | null;
  output?: number | null;
  /** "12,3 k" for large values. */
  compact?: boolean;
  /** Append the "tokens" unit (default true). */
  unit?: boolean;
}

/** Token count with the input / output breakdown in the tooltip. */
export function TokenCount({ total, input, output, compact = true, unit = true, className, muted }: TokenCountProps) {
  const hasIn = typeof input === "number" && Number.isFinite(input);
  const hasOut = typeof output === "number" && Number.isFinite(output);
  const value = typeof total === "number" && Number.isFinite(total) ? total : hasIn || hasOut ? (input ?? 0) + (output ?? 0) : null;
  if (value === null) return <span className={cn("text-subtle-foreground", className)}>—</span>;
  const text = formatTokens(value, { compact, unit });
  const content = (
    <span className={cn("whitespace-nowrap tabular-nums", muted && "text-muted-foreground", className)}>{text}</span>
  );
  if (!hasIn && !hasOut) return content;
  return (
    <SimpleTooltip
      content={
        <span className="grid gap-0.5 tabular-nums">
          <span>Entrée : {formatTokens(input, { unit: false })}</span>
          <span>Sortie : {formatTokens(output, { unit: false })}</span>
          <span className="font-medium">Total : {formatTokens(value)}</span>
        </span>
      }
    >
      {content}
    </SimpleTooltip>
  );
}
