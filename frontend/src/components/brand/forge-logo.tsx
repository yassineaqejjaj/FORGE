"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/** Anvil silhouette (horn on the left, flared base), 32×32 grid. */
export const ANVIL_PATH =
  "M5 12.6C7.5 12.2 9 12 10.5 12H26v3c0 .9-.7 1.5-1.6 1.5h-2.9c-1.1.9-1.7 2.1-1.7 3.5v1.6l2.8 1.8c.6.4.9 1 .9 1.6v1H8.5v-1c0-.6.3-1.2.9-1.6l2.8-1.8V20c0-1.4-.6-2.6-1.7-3.5C8.6 15.9 6.6 14.6 5 12.6Z";
/** Four-point spark above the anvil. */
export const SPARK_PATH = "M20 3.2l.85 2.6 2.6.85-2.6.85L20 10.1l-.85-2.6-2.6-.85 2.6-.85Z";

export interface ForgeMarkProps extends React.SVGProps<SVGSVGElement> {
  /** "tile": white anvil on an orange gradient tile (app icon). "bare": brand-coloured anvil on transparent. */
  variant?: "tile" | "bare";
  /** Accessible title; omit when the mark sits next to the wordmark. */
  title?: string;
  /** Gently pulse the spark (splash screen). */
  animated?: boolean;
}

/** FORGE mark — an anvil struck by a spark. */
export function ForgeMark({ variant = "tile", title, animated = false, className, ...props }: ForgeMarkProps) {
  const uid = React.useId().replace(/:/g, "");
  const tileId = `forge-tile-${uid}`;
  const anvilId = `forge-anvil-${uid}`;
  const tile = variant === "tile";

  return (
    <svg
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      className={cn("shrink-0", className)}
      {...props}
    >
      {title ? <title>{title}</title> : null}
      <defs>
        <linearGradient id={tileId} x1="3" y1="1" x2="29" y2="31" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#FDBA74" />
          <stop offset="0.45" stopColor="#F97316" />
          <stop offset="1" stopColor="#9A3412" />
        </linearGradient>
        <linearGradient id={anvilId} x1="16" y1="12" x2="16" y2="26" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#FFFFFF" />
          <stop offset="1" stopColor="#FFEDD5" />
        </linearGradient>
      </defs>

      {tile ? <rect width="32" height="32" rx="8" fill={`url(#${tileId})`} /> : null}

      <path d={ANVIL_PATH} fill={tile ? `url(#${anvilId})` : "var(--brand)"} />
      {/* Striking face highlight */}
      <path d="M10.5 12H26v1.2H9.2c.4-.6.8-1 1.3-1.2Z" fill={tile ? "#FFF7ED" : "var(--ember)"} opacity={tile ? 0.9 : 0.8} />

      <g className={animated ? "animate-ember" : undefined}>
        <path d={SPARK_PATH} fill={tile ? "#FEF3C7" : "var(--ember)"} />
        <circle cx="14.6" cy="7.4" r="0.95" fill={tile ? "#FFEDD5" : "var(--ember)"} />
        <circle cx="25" cy="9.3" r="0.75" fill={tile ? "#FFEDD5" : "var(--ember)"} />
      </g>
    </svg>
  );
}

export interface ForgeLogoProps {
  className?: string;
  /** Mark size in px (default 28). */
  size?: number;
  /** Hide the tagline under the wordmark. */
  hideTagline?: boolean;
  tagline?: string;
}

/** Mark + "FORGE" wordmark (+ optional tagline). */
export function ForgeLogo({ className, size = 28, hideTagline = false, tagline = "Laboratoire d'évaluation" }: ForgeLogoProps) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <ForgeMark width={size} height={size} />
      <span className="grid leading-none" aria-hidden>
        <span className="text-[15px] font-semibold tracking-[0.16em] text-foreground">FORGE</span>
        {!hideTagline ? (
          <span className="mt-1 text-[10.5px] font-medium tracking-wide text-subtle-foreground">{tagline}</span>
        ) : null}
      </span>
      <span className="sr-only">FORGE — Laboratoire d&apos;évaluation des agents IA</span>
    </span>
  );
}

/** The three NOVA programme constellation dots (NOVA Core red, ORBIT teal, FORGE orange). */
export function ConstellationDots({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1", className)} aria-hidden>
      <span className="size-1.5 rounded-full bg-nova" />
      <span className="size-1.5 rounded-full bg-orbit" />
      <span className="size-1.5 rounded-full bg-forge" />
    </span>
  );
}
