import type { ApiFieldError } from "@/lib/api/types";

/** Strip transport prefixes so "body.content.rules[0].type" and "rules[0].type" compare equal. */
export function normalizeFieldPath(field: string, stripPrefixes: readonly string[] = ["body.", "content."]): string {
  let f = field.trim();
  let changed = true;
  while (changed) {
    changed = false;
    for (const p of stripPrefixes) {
      if (f.startsWith(p)) {
        f = f.slice(p.length);
        changed = true;
      }
    }
  }
  return f;
}

/** Field errors whose (normalized) path is `prefix` or below it ("rules[1]" → "rules[1].params"). */
export function errorsUnder(errors: ReadonlyArray<ApiFieldError>, prefix: string, strip?: readonly string[]): ApiFieldError[] {
  return errors.filter((e) => {
    const f = normalizeFieldPath(e.field, strip);
    return f === prefix || f.startsWith(`${prefix}.`) || f.startsWith(`${prefix}[`);
  });
}

/** First message for an exact (normalized) path, or below it when `deep`. */
export function fieldError(
  errors: ReadonlyArray<ApiFieldError>,
  path: string,
  options: { deep?: boolean; strip?: readonly string[] } = {},
): string | undefined {
  const list = options.deep
    ? errorsUnder(errors, path, options.strip)
    : errors.filter((e) => normalizeFieldPath(e.field, options.strip) === path);
  if (!list.length) return undefined;
  return list.map((e) => (normalizeFieldPath(e.field, options.strip) === path ? e.message : `${normalizeFieldPath(e.field, options.strip)} : ${e.message}`)).join(" · ");
}
