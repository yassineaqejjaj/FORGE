/**
 * French (fr-FR) formatters for dates, durations, numbers, tokens, costs and sizes.
 * All functions accept null/undefined and return an em dash placeholder.
 */
import { format as formatDateFns, formatDistanceToNowStrict, isValid, parseISO } from "date-fns";
import { fr } from "date-fns/locale";

export const EMPTY = "—";
const LOCALE = "fr-FR";

type DateInput = string | number | Date | null | undefined;

export function toDate(value: DateInput): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const d = value instanceof Date ? value : typeof value === "number" ? new Date(value) : parseISO(value);
  return isValid(d) ? d : null;
}

/** "23 sept. 2026" */
export function formatDate(value: DateInput): string {
  const d = toDate(value);
  return d ? formatDateFns(d, "d MMM yyyy", { locale: fr }) : EMPTY;
}

/** "23 septembre 2026" */
export function formatDateLong(value: DateInput): string {
  const d = toDate(value);
  return d ? formatDateFns(d, "d MMMM yyyy", { locale: fr }) : EMPTY;
}

/** "23 sept. 2026 à 14:05" */
export function formatDateTime(value: DateInput): string {
  const d = toDate(value);
  return d ? formatDateFns(d, "d MMM yyyy 'à' HH:mm", { locale: fr }) : EMPTY;
}

/** "23/09/2026 14:05:12" — dense tables, audit logs. */
export function formatDateTimePrecise(value: DateInput): string {
  const d = toDate(value);
  return d ? formatDateFns(d, "dd/MM/yyyy HH:mm:ss", { locale: fr }) : EMPTY;
}

/** "14:05" */
export function formatTime(value: DateInput): string {
  const d = toDate(value);
  return d ? formatDateFns(d, "HH:mm", { locale: fr }) : EMPTY;
}

/** Short axis label for daily series: "23 sept." */
export function formatDayShort(value: DateInput): string {
  const d = toDate(value);
  return d ? formatDateFns(d, "d MMM", { locale: fr }) : EMPTY;
}

/** "il y a 3 minutes", "dans 2 jours", "à l'instant". */
export function formatRelative(value: DateInput, now: Date = new Date()): string {
  const d = toDate(value);
  if (!d) return EMPTY;
  const diffSec = Math.abs(now.getTime() - d.getTime()) / 1000;
  if (diffSec < 45) return "à l'instant";
  return formatDistanceToNowStrict(d, { addSuffix: true, locale: fr });
}

/** Age in whole days (e.g. freshness): 0 for today. */
export function ageInDays(value: DateInput, now: Date = new Date()): number | null {
  const d = toDate(value);
  if (!d) return null;
  return Math.max(0, Math.floor((now.getTime() - d.getTime()) / 86_400_000));
}

/** "12 j", "1 j", "aujourd'hui". */
export function formatAgeDays(value: DateInput): string {
  const days = ageInDays(value);
  if (days === null) return EMPTY;
  if (days === 0) return "aujourd'hui";
  return `${formatNumber(days)} j`;
}

const numberFormatters = new Map<string, Intl.NumberFormat>();
function nf(options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = JSON.stringify(options);
  let f = numberFormatters.get(key);
  if (!f) {
    f = new Intl.NumberFormat(LOCALE, options);
    numberFormatters.set(key, f);
  }
  return f;
}

function isNum(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** "12 345", "3,5" (max 2 decimals by default). */
export function formatNumber(value: number | null | undefined, maximumFractionDigits = 2): string {
  return isNum(value) ? nf({ maximumFractionDigits }).format(value) : EMPTY;
}

/** Compact: "1,2 k", "3,4 M". */
export function formatCompact(value: number | null | undefined): string {
  return isNum(value) ? nf({ notation: "compact", maximumFractionDigits: 1 }).format(value) : EMPTY;
}

/** Ratio 0..1 → "42 %" (use `digits` for decimals). */
export function formatPercent(ratio: number | null | undefined, digits = 0): string {
  return isNum(ratio)
    ? nf({ style: "percent", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(ratio)
    : EMPTY;
}

/** Normalised score 0..1 → "0,82". */
export function formatScore(value: number | null | undefined, digits = 2): string {
  return isNum(value) ? nf({ minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value) : EMPTY;
}

/** Milliseconds → "842 ms", "1,2 s", "12 s", "2 min 03 s", "1 h 03 min". */
export function formatMs(ms: number | null | undefined): string {
  if (!isNum(ms)) return EMPTY;
  const abs = Math.abs(ms);
  const sign = ms < 0 ? "−" : "";
  if (abs < 1) return `${sign}${nf({ maximumFractionDigits: 2 }).format(abs)} ms`;
  if (abs < 1000) return `${sign}${nf({ maximumFractionDigits: 0 }).format(abs)} ms`;
  const s = abs / 1000;
  if (s < 59.95) return `${sign}${nf({ maximumFractionDigits: s < 10 ? 1 : 0 }).format(s)} s`;
  const totalSec = Math.round(s);
  const m = Math.floor(totalSec / 60);
  const rs = totalSec % 60;
  if (m < 60) return `${sign}${m} min ${String(rs).padStart(2, "0")} s`;
  const h = Math.floor(m / 60);
  return `${sign}${h} h ${String(m % 60).padStart(2, "0")} min`;
}

/** Alias kept for readability in latency contexts. */
export const formatDuration = formatMs;

/** Tokens → "3 420 tokens" (or compact "3,4 k tokens" when `compact`). */
export function formatTokens(value: number | null | undefined, options: { compact?: boolean; unit?: boolean } = {}): string {
  if (!isNum(value)) return EMPTY;
  const { compact = false, unit = true } = options;
  const n = compact && Math.abs(value) >= 10_000 ? formatCompact(value) : formatNumber(Math.round(value), 0);
  if (!unit) return n;
  return `${n} ${Math.abs(value) >= 2 || value === 0 ? "tokens" : "token"}`;
}

export type Currency = "EUR" | "USD";

/** Fraction digits adapted to the magnitude so that tiny LLM costs stay readable. */
function costDigits(abs: number): number {
  if (abs === 0) return 2;
  if (abs < 0.0001) return 6;
  if (abs < 0.01) return 4;
  if (abs < 1) return 3;
  return 2;
}

/** Cost with adaptive precision (fr-FR): "12,40 €", "0,0042 €", "0,000031 $". Accepts numeric strings (Decimal). */
export function formatCost(value: number | string | null | undefined, currency: Currency | string = "EUR"): string {
  const n = typeof value === "string" ? Number(value) : value;
  if (!isNum(n)) return EMPTY;
  const code = (currency || "EUR").toUpperCase();
  const digits = costDigits(Math.abs(n));
  try {
    return nf({ style: "currency", currency: code, minimumFractionDigits: 2, maximumFractionDigits: digits }).format(n);
  } catch {
    // Unknown ISO code: number + raw code.
    return `${nf({ minimumFractionDigits: 2, maximumFractionDigits: digits }).format(n)} ${code}`;
  }
}

/** Composite / dimension score on the 0–100 scale → "78,4" (one decimal by default). */
export function formatScore100(value: number | null | undefined, digits = 1): string {
  return isNum(value) ? nf({ minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value) : EMPTY;
}

/**
 * Signed number with a typographic minus: "+3,2", "−1,5", "0".
 * `unit` is appended with a narrow no-break space ("+3,2 pts", "−12 %").
 */
export function formatSigned(value: number | null | undefined, options: { digits?: number; unit?: string } = {}): string {
  if (!isNum(value)) return EMPTY;
  const { digits = 1, unit } = options;
  const rounded = Number(value.toFixed(digits));
  const body = nf({ minimumFractionDigits: 0, maximumFractionDigits: digits }).format(Math.abs(rounded));
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "";
  return `${sign}${body}${unit ? `\u202f${unit}` : ""}`;
}

/** Signed ratio → "+12 %", "−3,5 %". */
export function formatSignedPercent(ratio: number | null | undefined, digits = 0): string {
  if (!isNum(ratio)) return EMPTY;
  const pct = ratio * 100;
  return formatSigned(pct, { digits, unit: "%" });
}

/** p-value → "p = 0,032", "p < 0,001". */
export function formatPValue(p: number | null | undefined): string {
  if (!isNum(p)) return EMPTY;
  if (p < 0.001) return "p < 0,001";
  return `p = ${nf({ minimumFractionDigits: 3, maximumFractionDigits: 3 }).format(p)}`;
}

/** Confidence interval → "[−1,2 ; 4,8]". */
export function formatInterval(low: number | null | undefined, high: number | null | undefined, digits = 1): string {
  if (!isNum(low) || !isNum(high)) return EMPTY;
  const f = (v: number) => (v < 0 ? "−" : "") + nf({ minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Math.abs(v));
  return `[${f(low)} ; ${f(high)}]`;
}

const BYTE_UNITS = ["o", "Ko", "Mo", "Go", "To"] as const;

/** Bytes → "512 o", "1,2 Mo" (French octet units, base 1024). */
export function formatBytes(bytes: number | null | undefined): string {
  if (!isNum(bytes)) return EMPTY;
  if (bytes < 1024) return `${formatNumber(bytes, 0)} o`;
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${nf({ maximumFractionDigits: value < 10 ? 1 : 0 }).format(value)} ${BYTE_UNITS[unit]}`;
}

/** Pluralize a French noun: plural(3, "document") → "3 documents". */
export function plural(count: number | null | undefined, singular: string, pluralForm?: string): string {
  const n = isNum(count) ? count : 0;
  const word = Math.abs(n) >= 2 ? (pluralForm ?? `${singular}s`) : singular;
  return `${formatNumber(n, 0)} ${word}`;
}

/** Truncate text with an ellipsis. */
export function truncate(value: string | null | undefined, max = 120): string {
  if (!value) return "";
  return value.length > max ? `${value.slice(0, max - 1).trimEnd()}…` : value;
}

/** Short UUID for display: "3f2a9c1e". */
export function shortId(id: string | null | undefined): string {
  return id ? id.replace(/-/g, "").slice(0, 8) : EMPTY;
}
