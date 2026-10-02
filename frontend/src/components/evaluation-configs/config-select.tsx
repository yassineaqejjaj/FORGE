"use client";

import * as React from "react";

import { SimpleSelect } from "@/components/ui/select";
import { useEvaluationConfigs } from "@/lib/api/evaluation-configs";

export const DEFAULT_CONFIG_VALUE = "__default__";

/** Select of the latest evaluation configurations (`is_default` flagged). Empty value = default config. */
export function EvaluationConfigSelect({
  id,
  value,
  onChange,
  allowDefault = true,
  defaultLabel = "Configuration par défaut",
  invalid,
}: {
  id?: string;
  value: string | null;
  onChange: (value: string | null) => void;
  allowDefault?: boolean;
  defaultLabel?: string;
  invalid?: boolean;
}) {
  const configs = useEvaluationConfigs({ page_size: 200, latest_only: true });
  const options = [
    ...(allowDefault ? [{ value: DEFAULT_CONFIG_VALUE, label: defaultLabel, description: "Résolue par l'API" }] : []),
    ...(configs.data?.items ?? []).map((c) => ({
      value: c.id,
      label: `${c.name} (v${c.version})`,
      description: `${c.key}${c.is_default ? " · par défaut" : ""} · seuil ${c.pass_threshold}`,
    })),
  ];
  return (
    <SimpleSelect
      id={id}
      invalid={invalid}
      placeholder={configs.isPending ? "Chargement…" : "Configuration…"}
      value={value ?? (allowDefault ? DEFAULT_CONFIG_VALUE : undefined)}
      options={options}
      onValueChange={(v) => onChange(v === DEFAULT_CONFIG_VALUE ? null : v)}
    />
  );
}
