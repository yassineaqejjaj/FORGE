"use client";

import { cn } from "@/lib/utils";

/** Width / height of the "forge" wordmark artwork (public/brand/forge-wordmark-mask.png). */
export const WORDMARK_RATIO = 634 / 278;

export interface ForgeWordmarkProps {
  /** Height in px (the width follows the artwork ratio). */
  height?: number;
  /** "auto": follows the theme; "on-dark": always the light-on-dark colours (dark brand panels). */
  tone?: "auto" | "on-dark";
  /** Gently pulse (splash screen). */
  animated?: boolean;
  /** Accessible name; pass `null` when the surrounding element already names FORGE. */
  label?: string | null;
  className?: string;
}

/**
 * The "forge" wordmark. The artwork is used as a CSS mask filled with the brand gradient (red → violet),
 * so the violet end can be lightened in dark mode instead of disappearing on a dark background.
 */
export function ForgeWordmark({ height = 24, tone = "auto", animated = false, label = "FORGE", className }: ForgeWordmarkProps) {
  return (
    <span
      role={label ? "img" : undefined}
      aria-label={label ?? undefined}
      aria-hidden={label ? undefined : true}
      className={cn(
        "forge-wordmark inline-block shrink-0",
        tone === "on-dark" && "forge-wordmark-on-dark",
        animated && "motion-safe:animate-pulse",
        className,
      )}
      style={{ height, width: Math.round(height * WORDMARK_RATIO) }}
    />
  );
}

/** Width / height of the "F" mark artwork (public/brand/forge-f-mask.png; app icon: src/app/icon.png). */
export const MARK_RATIO = 177 / 256;

/** The "F" mark alone (collapsed sidebar and other square spots), same gradient as the wordmark. */
export function ForgeMark({ height = 24, tone = "auto", label = "FORGE", className }: Omit<ForgeWordmarkProps, "animated">) {
  return (
    <span
      role={label ? "img" : undefined}
      aria-label={label ?? undefined}
      aria-hidden={label ? undefined : true}
      className={cn("forge-wordmark forge-mark inline-block shrink-0", tone === "on-dark" && "forge-wordmark-on-dark", className)}
      style={{ height, width: Math.round(height * MARK_RATIO) }}
    />
  );
}

export interface ForgeLogoProps {
  className?: string;
  /** Wordmark height in px (default 26). */
  size?: number;
  /** Hide the tagline under the wordmark. */
  hideTagline?: boolean;
  tagline?: string;
}

/** "forge" wordmark (+ optional tagline). */
export function ForgeLogo({ className, size = 26, hideTagline = false, tagline = "Laboratoire d'évaluation" }: ForgeLogoProps) {
  return (
    <span className={cn("inline-grid justify-items-start gap-1 leading-none", className)}>
      <ForgeWordmark height={size} label={null} />
      {!hideTagline ? (
        <span className="text-[10.5px] font-medium tracking-wide text-subtle-foreground" aria-hidden>
          {tagline}
        </span>
      ) : null}
      <span className="sr-only">FORGE — Laboratoire d&apos;évaluation des agents IA</span>
    </span>
  );
}
