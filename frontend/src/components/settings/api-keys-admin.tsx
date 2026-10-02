"use client";

import * as React from "react";
import { Ban, KeyRound, Plus, ShieldAlert } from "lucide-react";

import { TableSkeleton } from "@/components/benchmarks/common";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { RoleBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CodeBlock } from "@/components/ui/code-block";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Pagination } from "@/components/ui/pagination";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorMessage } from "@/lib/api/client";
import { useForgeMeta } from "@/lib/api/evaluation-configs";
import { useApiKeys, useCreateApiKey, useRevokeApiKey, type ApiKey, type ApiKeyCreated } from "@/lib/api/settings";
import type { Role } from "@/lib/enums";
import { formatDate, formatDateTime } from "@/lib/format";
import { ClearanceSelect, RoleSelect, SectionHeading } from "./common";

const PAGE_SIZE = 25;

function keyStatus(k: ApiKey): { label: string; tone: "green" | "red" | "neutral" | "amber" } {
  if (k.revoked_at) return { label: "Révoquée", tone: "red" };
  if (!k.active) return { label: "Expirée", tone: "neutral" };
  if (k.expires_at && new Date(k.expires_at).getTime() - Date.now() < 7 * 86_400_000) return { label: "Expire bientôt", tone: "amber" };
  return { label: "Active", tone: "green" };
}

function CreateKeyDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; onCreated: (k: ApiKeyCreated) => void }) {
  const create = useCreateApiKey();
  const [name, setName] = React.useState("");
  const [role, setRole] = React.useState<Role>("editor");
  const [clearance, setClearance] = React.useState(1);
  const [scope, setScope] = React.useState<"full" | "traces">("full");
  const [expires, setExpires] = React.useState("");
  const [submitted, setSubmitted] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setName("");
      setRole("editor");
      setClearance(1);
      setScope("full");
      setExpires("");
      setSubmitted(false);
      create.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset on open
  }, [open]);

  const nameError = !name.trim() ? "Le nom est obligatoire." : undefined;
  const expiresDate = expires ? new Date(`${expires}T23:59:59`) : null;
  const expiresError = expiresDate && expiresDate.getTime() < Date.now() ? "La date doit être future." : undefined;

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent size="md">
        <form
          className="grid gap-4"
          noValidate
          onSubmit={async (e) => {
            e.preventDefault();
            setSubmitted(true);
            if (nameError || expiresError) return;
            try {
              const created = await create.mutateAsync({
                name: name.trim(),
                role,
                clearance,
                scopes: scope === "traces" ? ["traces:write"] : [],
                expires_at: expiresDate ? expiresDate.toISOString() : null,
              });
              onOpenChange(false);
              onCreated(created);
            } catch {
              // rendered inline
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>Nouvelle clé d&apos;API</DialogTitle>
            <DialogDescription>Clé de service pour la CI (rôle éditeur) ou pour les agents qui poussent leurs traces.</DialogDescription>
          </DialogHeader>
          <Field id="k-name" label="Nom" required error={submitted ? nameError : undefined}>
            <Input id="k-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="CI GitHub — product-agent" autoFocus />
          </Field>
          <Field id="k-scope" label="Portée">
            <SegmentedControl
              aria-label="Portée"
              fullWidth
              value={scope}
              onValueChange={setScope}
              options={[
                { value: "full", label: "Accès selon le rôle" },
                { value: "traces", label: "Traces uniquement" },
              ]}
            />
          </Field>
          {scope === "traces" ? (
            <Alert tone="sky">
              Scope <code className="font-mono">traces:write</code> : la clé ne peut que pousser des traces (OTLP ou JSON). À donner aux agents.
            </Alert>
          ) : null}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="k-role" label="Rôle" hint={scope === "full" ? "Éditeur pour lancer des expériences en CI" : undefined}>
              <RoleSelect id="k-role" value={role} onChange={setRole} />
            </Field>
            <Field id="k-clearance" label="Habilitation" hint="Doit couvrir les scénarios du benchmark">
              <ClearanceSelect id="k-clearance" value={clearance} onChange={setClearance} />
            </Field>
          </div>
          <Field id="k-expires" label="Expiration" hint="Vide = sans expiration" error={submitted ? expiresError : undefined}>
            <Input id="k-expires" type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
          </Field>
          {create.error ? <Alert tone="red">{errorMessage(create.error)}</Alert> : null}
          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={create.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={create.isPending}>
              Créer la clé
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Shown once right after creation: the full key is never retrievable again. */
function KeyRevealDialog({ created, onClose }: { created: ApiKeyCreated | null; onClose: () => void }) {
  const meta = useForgeMeta();
  const [acknowledged, setAcknowledged] = React.useState(false);
  React.useEffect(() => setAcknowledged(false), [created]);
  if (!created) return null;
  const header = meta.data?.api_key_header ?? "X-Forge-Key";
  return (
    <Dialog open onOpenChange={(o) => !o && acknowledged && onClose()}>
      <DialogContent size="lg" hideClose onEscapeKeyDown={(e) => !acknowledged && e.preventDefault()} onPointerDownOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>Clé « {created.name} » créée</DialogTitle>
          <DialogDescription>Copiez-la maintenant : seule son empreinte est conservée, elle ne sera plus jamais affichée.</DialogDescription>
        </DialogHeader>
        <Alert tone="amber" icon={<ShieldAlert aria-hidden />} title="Affichée une seule fois">
          Stockez-la dans le coffre de secrets de votre CI (ex. <code className="font-mono">FORGE_API_KEY</code>). Ne la collez jamais dans un
          dépôt, un ticket ou une conversation.
        </Alert>
        <CodeBlock code={created.key} title="Clé d'API" wrap />
        <CodeBlock
          language="bash"
          title="Utilisation"
          wrap
          code={`export FORGE_API_KEY="<clé copiée>"\nforge whoami\n# ou en HTTP : Authorization: Bearer $FORGE_API_KEY  (ou ${header})`}
        />
        <label className="flex items-center gap-2 text-[13px]">
          <Switch checked={acknowledged} onCheckedChange={setAcknowledged} />
          J&apos;ai copié la clé en lieu sûr
        </label>
        <DialogFooter>
          <Button onClick={onClose} disabled={!acknowledged}>
            Terminer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ApiKeysAdmin() {
  const [page, setPage] = React.useState(1);
  const [includeRevoked, setIncludeRevoked] = React.useState(false);
  const query = useApiKeys({ page, page_size: PAGE_SIZE, include_revoked: includeRevoked });
  const revoke = useRevokeApiKey();
  const [createOpen, setCreateOpen] = React.useState(false);
  const [created, setCreated] = React.useState<ApiKeyCreated | null>(null);
  const [toRevoke, setToRevoke] = React.useState<ApiKey | null>(null);

  return (
    <section aria-labelledby="settings-section-title" className="grid gap-4">
      <SectionHeading
        title="Clés d'API"
        description="Clés de service fgk_… pour la CI et pour les agents (scope traces:write). Seul le SHA-256 est stocké."
        actions={
          <Button leftIcon={<Plus aria-hidden />} onClick={() => setCreateOpen(true)}>
            Nouvelle clé
          </Button>
        }
      />
      <Card>
        <div className="flex items-center justify-end gap-2 border-b border-border p-3">
          <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <Switch
              size="sm"
              checked={includeRevoked}
              onCheckedChange={(c) => {
                setIncludeRevoked(c);
                setPage(1);
              }}
            />
            Afficher les clés révoquées
          </label>
        </div>
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} variant="plain" />
        ) : query.isPending ? (
          <TableSkeleton />
        ) : query.data.total === 0 && !includeRevoked ? (
          <EmptyState
            variant="plain"
            icon={<KeyRound />}
            title="Aucune clé d'API"
            description="Créez une clé éditeur pour la CI (forge experiment run --fail-on-regression)."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Clé</TableHead>
                <TableHead>Rôle · habilitation</TableHead>
                <TableHead>Portée</TableHead>
                <TableHead>État</TableHead>
                <TableHead className="hidden md:table-cell">Dernière utilisation</TableHead>
                <TableHead className="hidden lg:table-cell">Expiration</TableHead>
                <TableHead className="w-24">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.items.length === 0 ? (
                <TableEmptyRow colSpan={7}>Aucune clé.</TableEmptyRow>
              ) : (
                query.data.items.map((k) => {
                  const st = keyStatus(k);
                  return (
                    <TableRow key={k.id} className={k.revoked_at ? "opacity-60" : undefined}>
                      <TableCell>
                        <div className="grid gap-0.5">
                          <span className="font-medium">{k.name}</span>
                          <span className="font-mono text-xs text-muted-foreground">{k.masked_key}</span>
                          <span className="text-[11px] text-subtle-foreground">Créée le {formatDateTime(k.created_at)}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          <RoleBadge value={k.role} />
                          <ClassificationBadge level={k.clearance} showLabel={false} />
                        </div>
                      </TableCell>
                      <TableCell>
                        {k.scopes.length ? (
                          k.scopes.map((s) => (
                            <Badge key={s} mono tone="sky">
                              {s}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-xs text-muted-foreground">Selon le rôle</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge tone={st.tone} dot>
                          {st.label}
                        </Badge>
                      </TableCell>
                      <TableCell className="hidden text-xs text-muted-foreground md:table-cell">
                        <RelativeTime date={k.last_used_at} fallback="Jamais utilisée" />
                      </TableCell>
                      <TableCell className="hidden text-xs text-muted-foreground lg:table-cell">
                        {k.expires_at ? formatDate(k.expires_at) : "Aucune"}
                      </TableCell>
                      <TableCell className="text-right">
                        {!k.revoked_at ? (
                          <Button variant="destructive-outline" size="xs" leftIcon={<Ban aria-hidden />} onClick={() => setToRevoke(k)}>
                            Révoquer
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        )}
        {query.data && query.data.total > PAGE_SIZE ? (
          <div className="border-t border-border p-3">
            <Pagination page={page} pageSize={PAGE_SIZE} total={query.data.total} onPageChange={setPage} />
          </div>
        ) : null}
      </Card>

      <CreateKeyDialog open={createOpen} onOpenChange={setCreateOpen} onCreated={setCreated} />
      <KeyRevealDialog created={created} onClose={() => setCreated(null)} />
      <ConfirmDialog
        open={Boolean(toRevoke)}
        onOpenChange={(o) => !o && setToRevoke(null)}
        title={`Révoquer la clé « ${toRevoke?.name ?? ""} » ?`}
        description="Les appels utilisant cette clé seront refusés immédiatement. Cette action est irréversible."
        confirmLabel="Révoquer"
        destructive
        confirmPhrase={toRevoke?.prefix}
        onConfirm={async () => {
          if (!toRevoke) return;
          try {
            await revoke.mutateAsync(toRevoke.id);
            setToRevoke(null);
          } catch {
            // toast from the mutation cache
          }
        }}
      >
        <p className="text-[13px] text-muted-foreground">
          Clé <span className="font-mono">{toRevoke?.masked_key}</span>
        </p>
      </ConfirmDialog>
    </section>
  );
}
