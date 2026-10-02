"use client";

import * as React from "react";
import { Eye, EyeOff, Wand2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input, type InputProps } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { CLASSIFICATION_META, CLASSIFICATIONS, ROLE_META, ROLES, type Role } from "@/lib/enums";

/** Random temporary password (browser crypto), ≥ 10 characters as required by the API. */
export function generatePassword(length = 16): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_!@#%";
  const bytes = new Uint32Array(length);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join("");
}

/** Password / secret input with show-hide toggle and optional generator. */
export function SecretInput({ onGenerate, ...props }: InputProps & { onGenerate?: () => void }) {
  const [visible, setVisible] = React.useState(false);
  return (
    <div className="flex gap-2">
      <Input
        {...props}
        type={visible ? "text" : "password"}
        autoComplete="new-password"
        spellCheck={false}
        className="flex-1 font-mono"
        rightSlot={
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label={visible ? "Masquer" : "Afficher"}
            onClick={() => setVisible((v) => !v)}
          >
            {visible ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
          </Button>
        }
      />
      {onGenerate ? (
        <Button
          type="button"
          variant="secondary"
          leftIcon={<Wand2 aria-hidden />}
          onClick={() => {
            onGenerate();
            setVisible(true);
          }}
        >
          Générer
        </Button>
      ) : null}
    </div>
  );
}

export function RoleSelect({ id, value, onChange, disabled }: { id?: string; value: Role; onChange: (r: Role) => void; disabled?: boolean }) {
  return (
    <SimpleSelect
      id={id}
      disabled={disabled}
      value={value}
      onValueChange={onChange}
      options={ROLES.map((r) => ({ value: r, label: ROLE_META[r].label, description: ROLE_META[r].description }))}
    />
  );
}

export function ClearanceSelect({ id, value, onChange, max }: { id?: string; value: number; onChange: (c: number) => void; max?: number }) {
  return (
    <SimpleSelect
      id={id}
      value={String(value)}
      onValueChange={(v) => onChange(Number(v))}
      options={CLASSIFICATIONS.map((c) => ({
        value: String(c),
        label: `${CLASSIFICATION_META[c].code} · ${CLASSIFICATION_META[c].label}`,
        description: CLASSIFICATION_META[c].description,
        disabled: max !== undefined && c > max,
      }))}
    />
  );
}

export function SectionHeading({ title, description, actions }: { title: string; description: string; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="grid gap-1">
        <h2 id="settings-section-title" className="text-base font-semibold tracking-tight">
          {title}
        </h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
