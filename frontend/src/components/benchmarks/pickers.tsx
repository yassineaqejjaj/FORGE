"use client";

import * as React from "react";
import { Bot, ChevronDown, ChevronRight, Pin, Search, X } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { VisibilityBadge } from "@/components/domain/visibility-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimpleSelect } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import {
  useAgentOptions,
  useAgentVersionOptions,
  useScenarioOptions,
  useScenarioVersionOptions,
  type AgentVersionSummary,
  type ScenarioListItem,
} from "@/lib/api/benchmarks";
import { scenarioCategoryLabel } from "@/lib/enums";
import { formatDate, plural } from "@/lib/format";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/* Scenarios                                                                  */
/* -------------------------------------------------------------------------- */

export interface ScenarioSelection {
  scenario_id: string;
  scenario_version_id: string | null;
  /** Display info (not sent to the API). */
  name: string;
  visibility: string;
  classification: number;
  latest_version: number;
  pinned_version?: number | null;
}

export function scenarioSelectionFrom(s: ScenarioListItem): ScenarioSelection {
  return {
    scenario_id: s.id,
    scenario_version_id: null,
    name: s.name,
    visibility: s.visibility,
    classification: s.classification,
    latest_version: s.latest_version,
  };
}

function PinSelect({ selection, onChange }: { selection: ScenarioSelection; onChange: (s: ScenarioSelection) => void }) {
  const [open, setOpen] = React.useState(Boolean(selection.scenario_version_id));
  const versions = useScenarioVersionOptions(open ? selection.scenario_id : undefined);
  if (!open) {
    return (
      <Button variant="ghost" size="xs" leftIcon={<Pin aria-hidden />} onClick={() => setOpen(true)}>
        Épingler une version
      </Button>
    );
  }
  const options = [
    { value: "latest", label: `Dernière version (v${selection.latest_version})` },
    ...(versions.data ?? []).map((v) => ({
      value: v.id,
      label: `v${v.version}`,
      description: `${formatDate(v.created_at)}${v.changelog ? ` · ${v.changelog}` : ""}`,
    })),
  ];
  if (selection.scenario_version_id && !versions.data) {
    options.push({ value: selection.scenario_version_id, label: `v${selection.pinned_version ?? "?"}`, description: "" });
  }
  return (
    <SimpleSelect
      size="sm"
      className="w-48"
      aria-label={`Version du scénario ${selection.name}`}
      value={selection.scenario_version_id ?? "latest"}
      options={options}
      onValueChange={(v) => {
        const version = versions.data?.find((x) => x.id === v);
        onChange({
          ...selection,
          scenario_version_id: v === "latest" ? null : v,
          pinned_version: version?.version ?? null,
        });
      }}
    />
  );
}

export interface ScenarioMultiPickerProps {
  value: ScenarioSelection[];
  onChange: (value: ScenarioSelection[]) => void;
  /** Allow pinning a version (benchmarks). */
  allowPin?: boolean;
  id?: string;
  invalid?: boolean;
}

/** Searchable scenario multi-picker with optional version pinning. */
export function ScenarioMultiPicker({ value, onChange, allowPin = true, id, invalid }: ScenarioMultiPickerProps) {
  const [q, setQ] = React.useState("");
  const [visibility, setVisibility] = React.useState<"all" | "public" | "private" | "fresh">("all");
  const debounced = useDebouncedValue(q, 250);
  const query = useScenarioOptions({ q: debounced || undefined, visibility: visibility === "all" ? undefined : visibility });
  const selected = new Set(value.map((s) => s.scenario_id));
  const items = query.data?.items ?? [];

  const toggle = (s: ScenarioListItem) => {
    if (selected.has(s.id)) onChange(value.filter((x) => x.scenario_id !== s.id));
    else onChange([...value, scenarioSelectionFrom(s)]);
  };
  const allVisibleSelected = items.length > 0 && items.every((s) => selected.has(s.id));

  return (
    <div className={cn("grid gap-3 rounded-lg border border-border p-3", invalid && "border-destructive")} id={id}>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          size="sm"
          leftIcon={<Search aria-hidden />}
          placeholder="Rechercher un scénario…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="min-w-48 flex-1"
          aria-label="Rechercher un scénario"
        />
        <SegmentedControl
          size="sm"
          aria-label="Visibilité"
          value={visibility}
          onValueChange={setVisibility}
          options={[
            { value: "all", label: "Tous" },
            { value: "public", label: "Publics" },
            { value: "private", label: "Privés" },
            { value: "fresh", label: "Fresh" },
          ]}
        />
      </div>
      <div className="max-h-56 overflow-y-auto rounded-md border border-border">
        {query.isPending ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : items.length === 0 ? (
          <p className="px-3 py-6 text-center text-[13px] text-muted-foreground">Aucun scénario ne correspond.</p>
        ) : (
          <ul role="listbox" aria-multiselectable aria-label="Scénarios disponibles">
            <li className="flex items-center gap-2 border-b border-border bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground">
              <Checkbox
                checked={allVisibleSelected}
                onCheckedChange={() => {
                  if (allVisibleSelected) onChange(value.filter((v) => !items.some((s) => s.id === v.scenario_id)));
                  else onChange([...value, ...items.filter((s) => !selected.has(s.id)).map(scenarioSelectionFrom)]);
                }}
                aria-label="Tout sélectionner"
              />
              {plural(query.data?.total ?? items.length, "scénario")}
            </li>
            {items.map((s) => (
              <li key={s.id} role="option" aria-selected={selected.has(s.id)}>
                <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-[13px] hover:bg-muted/60">
                  <Checkbox checked={selected.has(s.id)} onCheckedChange={() => toggle(s)} />
                  <span className="min-w-0 flex-1 truncate">{s.name}</span>
                  <span className="hidden text-xs text-muted-foreground sm:inline">{scenarioCategoryLabel(s.category)}</span>
                  <VisibilityBadge visibility={s.visibility} iconOnly />
                  <ClassificationBadge level={s.classification} showLabel={false} />
                </label>
              </li>
            ))}
          </ul>
        )}
      </div>
      {value.length ? (
        <div className="grid gap-1.5">
          <p className="text-xs font-medium text-muted-foreground">{plural(value.length, "scénario sélectionné", "scénarios sélectionnés")}</p>
          <ul className="grid gap-1">
            {value.map((s) => (
              <li key={s.scenario_id} className="flex flex-wrap items-center gap-2 rounded-md bg-muted/50 px-2 py-1 text-[13px]">
                <VisibilityBadge visibility={s.visibility} iconOnly />
                <span className="min-w-0 flex-1 truncate">{s.name}</span>
                {allowPin ? <PinSelect selection={s} onChange={(n) => onChange(value.map((x) => (x.scenario_id === n.scenario_id ? n : x)))} /> : null}
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`Retirer ${s.name}`}
                  onClick={() => onChange(value.filter((x) => x.scenario_id !== s.scenario_id))}
                >
                  <X aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Agent versions                                                             */
/* -------------------------------------------------------------------------- */

export interface AgentVersionChoice {
  id: string;
  label: string;
  agent_id: string;
  content_hash: string;
  model?: string | null;
}

function AgentVersionsRows({
  agentId,
  agentName,
  selected,
  onToggle,
}: {
  agentId: string;
  agentName: string;
  selected: Set<string>;
  onToggle: (v: AgentVersionChoice) => void;
}) {
  const versions = useAgentVersionOptions(agentId);
  if (versions.isPending) {
    return (
      <div className="flex justify-center py-2">
        <Spinner />
      </div>
    );
  }
  const list = [...(versions.data ?? [])].sort((a, b) => b.version_number - a.version_number);
  if (!list.length) return <p className="px-9 py-1.5 text-xs text-muted-foreground">Aucune version.</p>;
  return (
    <ul>
      {list.map((v) => (
        <li key={v.id}>
          <label className="flex cursor-pointer items-center gap-2 py-1.5 pl-9 pr-3 text-[13px] hover:bg-muted/60">
            <Checkbox
              checked={selected.has(v.id)}
              onCheckedChange={() => onToggle(choiceFrom(v, agentName))}
              aria-label={`${agentName} v${v.version}`}
            />
            <span className="font-medium">v{v.version}</span>
            {v.model ? <span className="truncate text-xs text-muted-foreground">{v.model}</span> : null}
            <span className="ml-auto truncate text-xs text-subtle-foreground">{v.changelog}</span>
          </label>
        </li>
      ))}
    </ul>
  );
}

export function choiceFrom(v: AgentVersionSummary, agentName: string): AgentVersionChoice {
  return { id: v.id, label: `${agentName} v${v.version}`, agent_id: v.agent_id, content_hash: v.content_hash, model: v.model };
}

export interface AgentVersionMultiPickerProps {
  value: AgentVersionChoice[];
  onChange: (value: AgentVersionChoice[]) => void;
  id?: string;
  invalid?: boolean;
}

/** Agents (expandable) → versions (checkboxes). */
export function AgentVersionMultiPicker({ value, onChange, id, invalid }: AgentVersionMultiPickerProps) {
  const [q, setQ] = React.useState("");
  const debounced = useDebouncedValue(q, 250);
  const agents = useAgentOptions(debounced || undefined);
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const selected = new Set(value.map((v) => v.id));
  const toggle = (v: AgentVersionChoice) =>
    onChange(selected.has(v.id) ? value.filter((x) => x.id !== v.id) : [...value, v]);

  return (
    <div className={cn("grid gap-3 rounded-lg border border-border p-3", invalid && "border-destructive")} id={id}>
      <Input
        size="sm"
        leftIcon={<Search aria-hidden />}
        placeholder="Rechercher un agent…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        aria-label="Rechercher un agent"
      />
      <div className="max-h-56 overflow-y-auto rounded-md border border-border">
        {agents.isPending ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : !agents.data?.items.length ? (
          <p className="px-3 py-6 text-center text-[13px] text-muted-foreground">Aucun agent.</p>
        ) : (
          <ul>
            {agents.data.items.map((a) => {
              const open = expanded.has(a.id);
              return (
                <li key={a.id} className="border-b border-border last:border-b-0">
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none"
                    aria-expanded={open}
                    onClick={() =>
                      setExpanded((prev) => {
                        const next = new Set(prev);
                        if (next.has(a.id)) next.delete(a.id);
                        else next.add(a.id);
                        return next;
                      })
                    }
                  >
                    {open ? <ChevronDown className="size-3.5" aria-hidden /> : <ChevronRight className="size-3.5" aria-hidden />}
                    <Bot className="size-3.5 text-muted-foreground" aria-hidden />
                    <span className="font-medium">{a.name}</span>
                    <span className="ml-auto text-xs text-muted-foreground">{plural(a.versions_count, "version")}</span>
                  </button>
                  {open ? <AgentVersionsRows agentId={a.id} agentName={a.name} selected={selected} onToggle={toggle} /> : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {value.length ? (
        <div className="flex flex-wrap gap-1.5">
          {value.map((v) => (
            <Badge key={v.id} size="md" tone="blue" className="pr-0.5">
              {v.label}
              <button
                type="button"
                className="ml-0.5 rounded p-0.5 hover:bg-blue-500/15"
                aria-label={`Retirer ${v.label}`}
                onClick={() => onChange(value.filter((x) => x.id !== v.id))}
              >
                <X className="size-3" aria-hidden />
              </button>
            </Badge>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** Single agent version select (agent → version), used for baseline / candidate. */
export function AgentVersionSelect({
  value,
  onChange,
  id,
  invalid,
  label,
}: {
  value: AgentVersionChoice | null;
  onChange: (v: AgentVersionChoice | null) => void;
  id: string;
  invalid?: boolean;
  label: string;
}) {
  const agents = useAgentOptions();
  const [agentId, setAgentId] = React.useState<string | undefined>(value?.agent_id);
  React.useEffect(() => {
    if (value?.agent_id) setAgentId(value.agent_id);
  }, [value?.agent_id]);
  const versions = useAgentVersionOptions(agentId);
  const agentName = agents.data?.items.find((a) => a.id === agentId)?.name ?? "";
  const sorted = [...(versions.data ?? [])].sort((a, b) => b.version_number - a.version_number);
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <SimpleSelect
        id={id}
        invalid={invalid}
        aria-label={`${label} : agent`}
        placeholder={agents.isPending ? "Chargement…" : "Agent…"}
        value={agentId}
        options={(agents.data?.items ?? []).map((a) => ({ value: a.id, label: a.name, description: a.provider }))}
        onValueChange={(v) => {
          setAgentId(v);
          onChange(null);
        }}
      />
      <SimpleSelect
        aria-label={`${label} : version`}
        invalid={invalid}
        disabled={!agentId}
        placeholder={versions.isFetching ? "Chargement…" : "Version…"}
        value={value?.id}
        options={sorted.map((v) => ({
          value: v.id,
          label: `v${v.version}`,
          description: [v.model, v.changelog].filter(Boolean).join(" · ") || undefined,
        }))}
        onValueChange={(v) => {
          const found = sorted.find((x) => x.id === v);
          if (found) onChange(choiceFrom(found, agentName));
        }}
      />
    </div>
  );
}
