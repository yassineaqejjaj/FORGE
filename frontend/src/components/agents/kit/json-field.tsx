"use client";

import * as React from "react";
import { CircleCheck, CircleX, WandSparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export type JsonParseResult = { ok: true; value: unknown } | { ok: false; error: string };

/** Syntax check only (business validation is done by the API). Empty text → `empty`. */
export function parseJsonText(text: string, empty: unknown = undefined): JsonParseResult {
  if (!text.trim()) return { ok: true, value: empty };
  try {
    return { ok: true, value: JSON.parse(text) as unknown };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "JSON invalide" };
  }
}

/** Pretty JSON text for editors ("" for undefined / null when `blankWhenEmpty`). */
export function toJsonText(value: unknown, blankWhenEmpty = false): string {
  if (value === undefined) return "";
  if (blankWhenEmpty && (value === null || (typeof value === "object" && Object.keys(value as object).length === 0))) {
    return "";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "";
  }
}

export interface JsonFieldProps {
  id: string;
  label?: React.ReactNode;
  value: string;
  onChange: (value: string) => void;
  hint?: React.ReactNode;
  /** Server-side error for this field. */
  error?: React.ReactNode;
  rows?: number;
  placeholder?: string;
  /** Expected top-level shape (syntax hint only). */
  expect?: "object" | "array" | "any";
  disabled?: boolean;
  className?: string;
  labelAside?: React.ReactNode;
}

/** Monospace JSON editor with live syntax feedback and a "format" action. */
export function JsonField({
  id,
  label,
  value,
  onChange,
  hint,
  error,
  rows = 8,
  placeholder,
  expect = "any",
  disabled,
  className,
  labelAside,
}: JsonFieldProps) {
  const parsed = parseJsonText(value);
  const shapeError =
    parsed.ok && parsed.value !== undefined && expect !== "any"
      ? expect === "array"
        ? Array.isArray(parsed.value)
          ? null
          : "Un tableau JSON est attendu ([…])."
        : parsed.value !== null && typeof parsed.value === "object" && !Array.isArray(parsed.value)
          ? null
          : "Un objet JSON est attendu ({…})."
      : null;
  const syntaxError = !parsed.ok ? `JSON invalide : ${parsed.error}` : shapeError;

  return (
    <Field
      id={id}
      label={label}
      hint={hint}
      error={error ?? syntaxError ?? undefined}
      className={className}
      labelAside={
        <span className="inline-flex items-center gap-2">
          {labelAside}
          {value.trim() ? (
            parsed.ok && !shapeError ? (
              <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400">
                <CircleCheck className="size-3.5" aria-hidden /> JSON valide
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-destructive">
                <CircleX className="size-3.5" aria-hidden /> Invalide
              </span>
            )
          ) : null}
          <Button
            type="button"
            variant="ghost"
            size="xs"
            disabled={disabled || !parsed.ok || parsed.value === undefined}
            onClick={() => parsed.ok && onChange(toJsonText(parsed.value))}
            leftIcon={<WandSparkles aria-hidden />}
          >
            Formater
          </Button>
        </span>
      }
    >
      <Textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        placeholder={placeholder}
        spellCheck={false}
        disabled={disabled}
        invalid={Boolean(error || syntaxError)}
        aria-describedby={error || syntaxError ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={cn("font-mono text-[12.5px]")}
      />
    </Field>
  );
}
