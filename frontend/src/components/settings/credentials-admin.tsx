"use client";

import * as React from "react";
import { Lock, MoreHorizontal, Pencil, Plus, RefreshCw, Trash2, Vault } from "lucide-react";
import { toast } from "sonner";

import { TableSkeleton } from "@/components/benchmarks/common";
import { ProviderKindBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage, isApiError } from "@/lib/api/client";
import {
  useCreateCredential,
  useCredentials,
  useDeleteCredential,
  useUpdateCredential,
  type Credential,
  type CredentialUpdateInput,
} from "@/lib/api/settings";
import { PROVIDER_KIND_META, PROVIDER_KINDS, type ProviderKind } from "@/lib/enums";
import { SecretInput, SectionHeading } from "./common";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

interface HeaderRow {
  key: string;
  value: string;
}

function HeadersEditor({ rows, onChange }: { rows: HeaderRow[]; onChange: (rows: HeaderRow[]) => void }) {
  return (
    <div className="grid gap-2">
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2">
          <Input size="sm" aria-label="Nom de l'en-tête" placeholder="X-Api-Version" value={r.key} onChange={(e) => onChange(rows.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />
          <Input
            size="sm"
            type="password"
            autoComplete="new-password"
            aria-label="Valeur de l'en-tête"
            placeholder="valeur (chiffrée)"
            value={r.value}
            onChange={(e) => onChange(rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
          />
          <Button variant="ghost" size="icon-sm" aria-label="Retirer l'en-tête" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
            <Trash2 aria-hidden />
          </Button>
        </div>
      ))}
      <div>
        <Button variant="ghost" size="xs" leftIcon={<Plus aria-hidden />} onClick={() => onChange([...rows, { key: "", value: "" }])}>
          Ajouter un en-tête
        </Button>
      </div>
    </div>
  );
}

function headersObject(rows: HeaderRow[]): Record<string, string> | undefined {
  const entries = rows.filter((r) => r.key.trim()).map((r) => [r.key.trim(), r.value] as const);
  return entries.length ? Object.fromEntries(entries) : undefined;
}

function CredentialDialog({ open, onOpenChange, credential }: { open: boolean; onOpenChange: (o: boolean) => void; credential?: Credential | null }) {
  const editing = Boolean(credential);
  const create = useCreateCredential();
  const update = useUpdateCredential();
  const mutation = editing ? update : create;
  const [name, setName] = React.useState("");
  const [kind, setKind] = React.useState<ProviderKind>("anthropic");
  const [secret, setSecret] = React.useState("");
  const [clearSecret, setClearSecret] = React.useState(false);
  const [baseUrl, setBaseUrl] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [replaceHeaders, setReplaceHeaders] = React.useState(false);
  const [headers, setHeaders] = React.useState<HeaderRow[]>([]);
  const [submitted, setSubmitted] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setName(credential?.name ?? "");
    setKind((credential?.kind as ProviderKind) ?? "anthropic");
    setSecret("");
    setClearSecret(false);
    setBaseUrl(credential?.base_url ?? "");
    setDescription(credential?.description ?? "");
    setReplaceHeaders(!credential);
    setHeaders([]);
    setSubmitted(false);
    create.reset();
    update.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset on open
  }, [open]);

  const nameError = !NAME_RE.test(name) ? "Lettres, chiffres, « _ », « . », « - » (commence par une lettre ou un chiffre)." : undefined;
  const fe = isApiError(mutation.error) ? mutation.error.fieldErrors : {};

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (nameError) return;
    try {
      if (credential) {
        const body: CredentialUpdateInput = {};
        if (name !== credential.name) body.name = name;
        if (description !== credential.description) body.description = description;
        if (clearSecret) body.secret = "";
        else if (secret) body.secret = secret;
        if ((baseUrl || null) !== (credential.base_url ?? null)) body.base_url = baseUrl;
        if (replaceHeaders) body.headers = headersObject(headers) ?? {};
        await update.mutateAsync({ id: credential.id, body });
        toast.success(body.secret !== undefined || body.headers !== undefined ? "Identifiant mis à jour (rotation effectuée)" : "Identifiant mis à jour");
      } else {
        await create.mutateAsync({
          name,
          kind,
          secret: secret || null,
          base_url: baseUrl.trim() || null,
          headers: headersObject(headers) ?? null,
          description,
        });
      }
      onOpenChange(false);
    } catch {
      // rendered inline
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !mutation.isPending && onOpenChange(o)}>
      <DialogContent size="md">
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>{editing ? `Modifier « ${credential?.name} »` : "Nouvel identifiant fournisseur"}</DialogTitle>
            <DialogDescription>
              Les secrets sont chiffrés au repos et ne sont jamais renvoyés par l&apos;API : seule l&apos;empreinte ••••abcd est affichée.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="c-name" label="Nom" required error={submitted ? nameError : fe.name}>
              <Input id="c-name" className="font-mono" value={name} onChange={(e) => setName(e.target.value)} placeholder="anthropic-prod" autoFocus />
            </Field>
            <Field id="c-kind" label="Type" hint={editing ? "Non modifiable" : undefined}>
              <SimpleSelect
                id="c-kind"
                disabled={editing}
                value={kind}
                onValueChange={setKind}
                options={PROVIDER_KINDS.map((k) => ({ value: k, label: PROVIDER_KIND_META[k].label }))}
              />
            </Field>
          </div>
          <Field
            id="c-secret"
            label={editing ? "Nouveau secret (rotation)" : "Secret (clé ou jeton)"}
            hint={editing ? `Vide = secret inchangé${credential?.secret_hint ? ` (${credential.secret_hint})` : ""}.` : "Jamais réaffiché après l'enregistrement."}
            error={fe.secret}
          >
            <SecretInput id="c-secret" value={secret} disabled={clearSecret} onChange={(e) => setSecret(e.target.value)} placeholder={editing ? "••••••••" : "sk-…"} />
          </Field>
          {editing && credential?.has_secret ? (
            <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
              <Switch size="sm" checked={clearSecret} onCheckedChange={setClearSecret} />
              Effacer le secret enregistré
            </label>
          ) : null}
          <Field id="c-base-url" label="URL de base" hint="Optionnel : endpoint OpenAI-compatible, instance NOVA / ORBIT…" error={fe.base_url}>
            <Input id="c-base-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…" />
          </Field>
          <div className="grid gap-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[13px] font-medium">En-têtes supplémentaires (chiffrés)</span>
              {editing ? (
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Switch size="sm" checked={replaceHeaders} onCheckedChange={setReplaceHeaders} />
                  Remplacer {credential?.has_headers ? "les en-têtes existants" : ""}
                </label>
              ) : null}
            </div>
            {replaceHeaders ? <HeadersEditor rows={headers} onChange={setHeaders} /> : null}
          </div>
          <Field id="c-description" label="Description">
            <Textarea id="c-description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          {mutation.error ? <Alert tone="red">{errorMessage(mutation.error)}</Alert> : null}
          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              {editing ? "Enregistrer" : "Créer l'identifiant"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function CredentialsAdmin() {
  const query = useCredentials();
  const remove = useDeleteCredential();
  const [createOpen, setCreateOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Credential | null>(null);
  const [toDelete, setToDelete] = React.useState<Credential | null>(null);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);

  return (
    <section aria-labelledby="settings-section-title" className="grid gap-4">
      <SectionHeading
        title="Identifiants fournisseurs"
        description="Clés LLM, jetons NOVA / ORBIT et en-têtes HTTP, chiffrés et déchiffrés uniquement dans les workers au moment de l'appel."
        actions={
          <Button leftIcon={<Plus aria-hidden />} onClick={() => setCreateOpen(true)}>
            Nouvel identifiant
          </Button>
        }
      />
      <Card>
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} variant="plain" />
        ) : query.isPending ? (
          <TableSkeleton />
        ) : query.data.length === 0 ? (
          <EmptyState
            variant="plain"
            icon={<Vault />}
            title="Aucun identifiant"
            description="Ajoutez une clé Anthropic ou OpenAI-compatible pour activer les juges LLM et les agents pilotés par FORGE."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Identifiant</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Secret</TableHead>
                <TableHead className="hidden md:table-cell">Utilisé par</TableHead>
                <TableHead className="hidden lg:table-cell">Dernière rotation</TableHead>
                <TableHead className="w-12">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.map((c) => (
                <TableRow key={c.id}>
                  <TableCell>
                    <div className="grid gap-0.5">
                      <span className="font-mono font-medium">{c.name}</span>
                      {c.base_url ? <span className="break-all text-xs text-muted-foreground">{c.base_url}</span> : null}
                      {c.description ? <span className="text-xs text-muted-foreground">{c.description}</span> : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <ProviderKindBadge value={c.kind} />
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-1">
                      {c.has_secret ? (
                        <Badge mono icon={<Lock aria-hidden />}>
                          {c.secret_hint ?? "••••"}
                        </Badge>
                      ) : (
                        <Badge tone="neutral">Aucun secret</Badge>
                      )}
                      {c.has_headers ? <Badge tone="sky">En-têtes</Badge> : null}
                    </div>
                  </TableCell>
                  <TableCell className="hidden text-[13px] md:table-cell">
                    {c.agent_versions_count || c.judges_count ? (
                      <span>
                        {c.agent_versions_count} version(s) d&apos;agent · {c.judges_count} juge(s)
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">Non utilisé</span>
                    )}
                  </TableCell>
                  <TableCell className="hidden text-xs text-muted-foreground lg:table-cell">
                    <RelativeTime date={c.rotated_at ?? c.created_at} />
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label={`Actions pour ${c.name}`}>
                          <MoreHorizontal aria-hidden />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => setEditing(c)}>
                          <RefreshCw aria-hidden /> Faire tourner le secret
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => setEditing(c)}>
                          <Pencil aria-hidden /> Modifier
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          onSelect={() => {
                            setDeleteError(null);
                            setToDelete(c);
                          }}
                          className="text-destructive"
                        >
                          <Trash2 aria-hidden /> Supprimer
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <CredentialDialog open={createOpen} onOpenChange={setCreateOpen} />
      <CredentialDialog open={Boolean(editing)} onOpenChange={(o) => !o && setEditing(null)} credential={editing} />
      <ConfirmDialog
        open={Boolean(toDelete)}
        onOpenChange={(o) => !o && setToDelete(null)}
        title={`Supprimer l'identifiant « ${toDelete?.name ?? ""} » ?`}
        description="Le secret chiffré est détruit. Impossible si une version d'agent ou un juge l'utilise encore."
        confirmLabel="Supprimer"
        destructive
        confirmPhrase={toDelete?.name}
        onConfirm={async () => {
          if (!toDelete) return;
          try {
            await remove.mutateAsync(toDelete.id);
            toast.success("Identifiant supprimé");
            setToDelete(null);
          } catch (error) {
            setDeleteError(errorMessage(error));
          }
        }}
      >
        {toDelete && (toDelete.agent_versions_count || toDelete.judges_count) ? (
          <Alert tone="amber">
            Utilisé par {toDelete.agent_versions_count} version(s) d&apos;agent et {toDelete.judges_count} juge(s) : la suppression sera refusée.
          </Alert>
        ) : null}
        {deleteError ? <Alert tone="red">{deleteError}</Alert> : null}
      </ConfirmDialog>
    </section>
  );
}
