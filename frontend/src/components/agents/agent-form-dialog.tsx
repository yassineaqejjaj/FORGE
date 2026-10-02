"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useCreateAgent, useUpdateAgent, type Agent } from "@/lib/api/agents";
import { isApiError } from "@/lib/api/client";
import { slugify } from "@/lib/utils";

import { fieldError } from "./kit/field-errors";
import { JsonField, parseJsonText, toJsonText } from "./kit/json-field";
import { TagInput } from "./kit/tag-input";

export interface AgentFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Edit mode when provided (metadata only — behaviour changes go through a new version). */
  agent?: Agent;
}

interface FormState {
  name: string;
  slug: string;
  provider: string;
  description: string;
  tags: string[];
  metadata: string;
}

function initialState(agent?: Agent): FormState {
  return {
    name: agent?.name ?? "",
    slug: agent?.slug ?? "",
    provider: agent?.provider ?? "",
    description: agent?.description ?? "",
    tags: agent?.tags ?? [],
    metadata: toJsonText(agent?.metadata ?? {}, true),
  };
}

/** Create an agent (editor+) or edit its non-behavioural metadata. */
export function AgentFormDialog({ open, onOpenChange, agent }: AgentFormDialogProps) {
  const router = useRouter();
  const editing = Boolean(agent);
  const [form, setForm] = React.useState<FormState>(() => initialState(agent));
  const [slugTouched, setSlugTouched] = React.useState(false);
  const create = useCreateAgent();
  const update = useUpdateAgent(agent?.id ?? "");
  const mutation = editing ? update : create;
  const error = mutation.error;
  const errors = isApiError(error) ? error.errors : [];

  React.useEffect(() => {
    if (open) {
      setForm(initialState(agent));
      setSlugTouched(false);
      create.reset();
      update.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, agent]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));
  const metadata = parseJsonText(form.metadata, {});
  const canSubmit = form.name.trim().length > 0 && metadata.ok && !mutation.isPending;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !metadata.ok) return;
    const meta = (metadata.value ?? {}) as Record<string, unknown>;
    if (editing && agent) {
      update.mutate(
        { name: form.name.trim(), provider: form.provider.trim(), description: form.description, tags: form.tags, metadata: meta },
        {
          onSuccess: () => {
            toast.success("Agent mis à jour");
            onOpenChange(false);
          },
        },
      );
    } else {
      create.mutate(
        {
          name: form.name.trim(),
          slug: form.slug.trim() || null,
          provider: form.provider.trim(),
          description: form.description,
          tags: form.tags,
          metadata: meta,
        },
        {
          onSuccess: (created) => {
            toast.success("Agent créé", { description: "Créez maintenant sa première version." });
            onOpenChange(false);
            router.push(`/agents/${created.id}/versions/new`);
          },
        },
      );
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !mutation.isPending && onOpenChange(o)}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{editing ? "Modifier l'agent" : "Nouvel agent"}</DialogTitle>
            <DialogDescription>
              {editing
                ? "Nom, description, fournisseur, étiquettes et métadonnées. Le comportement (prompt, modèle, outils…) se modifie en créant une nouvelle version."
                : "Un agent regroupe des versions immuables (prompt, modèle, outils, contexte, budget)."}
            </DialogDescription>
          </DialogHeader>

          {error && !errors.length ? <Alert tone="red" title="Enregistrement impossible">{error.detail}</Alert> : null}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="agent-name" label="Nom" required error={fieldError(errors, "name")}>
              <Input
                id="agent-name"
                value={form.name}
                onChange={(e) => {
                  set("name", e.target.value);
                  if (!editing && !slugTouched) set("slug", slugify(e.target.value));
                }}
                maxLength={200}
                required
                autoFocus
                invalid={Boolean(fieldError(errors, "name"))}
              />
            </Field>
            {!editing ? (
              <Field id="agent-slug" label="Identifiant (slug)" hint="Généré depuis le nom si vide." error={fieldError(errors, "slug")}>
                <Input
                  id="agent-slug"
                  value={form.slug}
                  onChange={(e) => {
                    setSlugTouched(true);
                    set("slug", e.target.value);
                  }}
                  maxLength={80}
                  className="font-mono"
                  invalid={Boolean(fieldError(errors, "slug"))}
                />
              </Field>
            ) : (
              <Field id="agent-slug-ro" label="Identifiant (slug)" hint="Non modifiable.">
                <Input id="agent-slug-ro" value={agent?.slug ?? ""} readOnly disabled className="font-mono" />
              </Field>
            )}
            <Field
              id="agent-provider"
              label="Fournisseur"
              hint="Organisation ou produit qui fournit l'agent (NOVA, équipe…)."
              error={fieldError(errors, "provider")}
              className="sm:col-span-2"
            >
              <Input id="agent-provider" value={form.provider} onChange={(e) => set("provider", e.target.value)} maxLength={200} />
            </Field>
            <Field id="agent-description" label="Description" error={fieldError(errors, "description")} className="sm:col-span-2">
              <Textarea
                id="agent-description"
                value={form.description}
                onChange={(e) => set("description", e.target.value)}
                rows={3}
                maxLength={5000}
              />
            </Field>
            <Field id="agent-tags" label="Étiquettes" hint="Entrée ou virgule pour ajouter." error={fieldError(errors, "tags", { deep: true })} className="sm:col-span-2">
              <TagInput id="agent-tags" value={form.tags} onChange={(v) => set("tags", v)} />
            </Field>
            <JsonField
              id="agent-metadata"
              label="Métadonnées (JSON)"
              value={form.metadata}
              onChange={(v) => set("metadata", v)}
              expect="object"
              rows={4}
              placeholder='{"equipe": "produit"}'
              error={fieldError(errors, "metadata", { deep: true })}
              className="sm:col-span-2"
            />
          </div>

          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={mutation.isPending} disabled={!canSubmit}>
              {editing ? "Enregistrer" : "Créer l'agent"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
