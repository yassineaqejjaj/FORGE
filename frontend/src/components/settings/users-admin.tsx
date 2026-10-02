"use client";

import * as React from "react";
import { KeyRound, MoreHorizontal, Pencil, Plus, Search, UserCheck, UserX } from "lucide-react";
import { toast } from "sonner";

import { TableSkeleton } from "@/components/benchmarks/common";
import { pageFrom, useUrlSearch, useUrlState } from "@/components/benchmarks/use-url-state";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { RoleBadge } from "@/components/domain/enum-badge";
import { RelativeTime } from "@/components/domain/relative-time";
import { UserAvatar } from "@/components/domain/user-avatar";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ErrorState } from "@/components/ui/error-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Pagination } from "@/components/ui/pagination";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableEmptyRow, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCurrentUser } from "@/hooks/use-current-user";
import { errorMessage, isApiError } from "@/lib/api/client";
import { useCreateUser, useUpdateUser, useUsers, type User } from "@/lib/api/settings";
import { ROLE_META, ROLES, type Role } from "@/lib/enums";
import { ClearanceSelect, generatePassword, RoleSelect, SecretInput, SectionHeading } from "./common";

const PAGE_SIZE = 25;
const ALL = "__all__";
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PASSWORD_MIN = 10;

function CreateUserDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const create = useCreateUser();
  const [email, setEmail] = React.useState("");
  const [fullName, setFullName] = React.useState("");
  const [role, setRole] = React.useState<Role>("viewer");
  const [clearance, setClearance] = React.useState(1);
  const [password, setPassword] = React.useState("");
  const [submitted, setSubmitted] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setEmail("");
      setFullName("");
      setRole("viewer");
      setClearance(1);
      setPassword("");
      setSubmitted(false);
      create.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset on open
  }, [open]);

  const errors = {
    email: !EMAIL_RE.test(email.trim()) ? "Adresse e-mail invalide." : undefined,
    fullName: !fullName.trim() ? "Le nom est obligatoire." : undefined,
    password: password.length < PASSWORD_MIN ? `Au moins ${PASSWORD_MIN} caractères.` : undefined,
  };
  const fe = isApiError(create.error) ? create.error.fieldErrors : {};

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (Object.values(errors).some(Boolean)) return;
    try {
      await create.mutateAsync({ email: email.trim(), full_name: fullName.trim(), role, clearance, password });
      onOpenChange(false);
    } catch {
      // rendered inline
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent size="md">
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>Nouvel utilisateur</DialogTitle>
            <DialogDescription>Transmettez le mot de passe temporaire par un canal sûr ; l&apos;utilisateur devra le changer.</DialogDescription>
          </DialogHeader>
          <Field id="u-email" label="E-mail" required error={submitted ? errors.email : fe.email}>
            <Input id="u-email" type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} invalid={submitted && Boolean(errors.email)} autoFocus />
          </Field>
          <Field id="u-name" label="Nom complet" required error={submitted ? errors.fullName : fe.full_name}>
            <Input id="u-name" value={fullName} onChange={(e) => setFullName(e.target.value)} invalid={submitted && Boolean(errors.fullName)} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="u-role" label="Rôle">
              <RoleSelect id="u-role" value={role} onChange={setRole} />
            </Field>
            <Field id="u-clearance" label="Habilitation" hint="Classification maximale visible">
              <ClearanceSelect id="u-clearance" value={clearance} onChange={setClearance} />
            </Field>
          </div>
          <Field id="u-password" label="Mot de passe temporaire" required error={submitted ? errors.password : fe.password} hint={`${PASSWORD_MIN} caractères minimum`}>
            <SecretInput id="u-password" value={password} onChange={(e) => setPassword(e.target.value)} onGenerate={() => setPassword(generatePassword())} />
          </Field>
          {create.error ? <Alert tone="red">{errorMessage(create.error)}</Alert> : null}
          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={create.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={create.isPending}>
              Créer l&apos;utilisateur
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditUserDialog({ user, onClose, isSelf }: { user: User | null; onClose: () => void; isSelf: boolean }) {
  const update = useUpdateUser();
  const [fullName, setFullName] = React.useState("");
  const [role, setRole] = React.useState<Role>("viewer");
  const [clearance, setClearance] = React.useState(1);

  React.useEffect(() => {
    if (user) {
      setFullName(user.full_name);
      setRole(user.role as Role);
      setClearance(user.clearance);
      update.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset per user
  }, [user]);

  if (!user) return null;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await update.mutateAsync({ id: user.id, body: { full_name: fullName.trim() || undefined, role, clearance } });
      toast.success("Utilisateur mis à jour");
      onClose();
    } catch {
      // rendered inline
    }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && !update.isPending && onClose()}>
      <DialogContent size="md">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Modifier {user.full_name}</DialogTitle>
            <DialogDescription>{user.email}</DialogDescription>
          </DialogHeader>
          <Field id="ue-name" label="Nom complet">
            <Input id="ue-name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="ue-role" label="Rôle" hint={isSelf ? "Vous modifiez votre propre compte." : undefined}>
              <RoleSelect id="ue-role" value={role} onChange={setRole} />
            </Field>
            <Field id="ue-clearance" label="Habilitation">
              <ClearanceSelect id="ue-clearance" value={clearance} onChange={setClearance} />
            </Field>
          </div>
          {isSelf && role !== "admin" ? (
            <Alert tone="amber">Vous allez perdre vos droits d&apos;administration à l&apos;enregistrement.</Alert>
          ) : null}
          {update.error ? <Alert tone="red">{errorMessage(update.error)}</Alert> : null}
          <DialogFooter>
            <Button variant="secondary" onClick={onClose} disabled={update.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={update.isPending}>
              Enregistrer
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordDialog({ user, onClose }: { user: User | null; onClose: () => void }) {
  const update = useUpdateUser();
  const [password, setPassword] = React.useState("");
  React.useEffect(() => {
    if (user) {
      setPassword("");
      update.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset per user
  }, [user]);
  if (!user) return null;
  const tooShort = password.length < PASSWORD_MIN;
  return (
    <Dialog open onOpenChange={(o) => !o && !update.isPending && onClose()}>
      <DialogContent size="md">
        <form
          className="grid gap-4"
          onSubmit={async (e) => {
            e.preventDefault();
            if (tooShort) return;
            try {
              await update.mutateAsync({ id: user.id, body: { password } });
              toast.success(`Mot de passe de ${user.full_name} réinitialisé`);
              onClose();
            } catch {
              // rendered inline
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>Réinitialiser le mot de passe</DialogTitle>
            <DialogDescription>
              {user.full_name} ({user.email}) — toutes ses sessions ouvertes seront révoquées.
            </DialogDescription>
          </DialogHeader>
          <Field id="ur-password" label="Nouveau mot de passe temporaire" hint={`${PASSWORD_MIN} caractères minimum`}>
            <SecretInput id="ur-password" value={password} onChange={(e) => setPassword(e.target.value)} onGenerate={() => setPassword(generatePassword())} autoFocus />
          </Field>
          {update.error ? <Alert tone="red">{errorMessage(update.error)}</Alert> : null}
          <DialogFooter>
            <Button variant="secondary" onClick={onClose} disabled={update.isPending}>
              Annuler
            </Button>
            <Button type="submit" variant="destructive" loading={update.isPending} disabled={tooShort}>
              Réinitialiser
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function UsersAdmin() {
  const { user: me } = useCurrentUser();
  const { get, set } = useUrlState();
  const search = useUrlSearch("q");
  const page = pageFrom(get("page"));
  const role = get("role") ?? undefined;
  const activeParam = get("active");
  const query = useUsers({ page, page_size: PAGE_SIZE, q: search.applied || undefined, role, active: activeParam === null ? undefined : activeParam === "true" });
  const update = useUpdateUser();
  const [createOpen, setCreateOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<User | null>(null);
  const [resetting, setResetting] = React.useState<User | null>(null);
  const [toggling, setToggling] = React.useState<User | null>(null);

  return (
    <section aria-labelledby="settings-section-title" className="grid gap-4">
      <SectionHeading
        title="Utilisateurs"
        description="Comptes, rôles (lecteur → administrateur) et habilitations C0–C3."
        actions={
          <Button leftIcon={<Plus aria-hidden />} onClick={() => setCreateOpen(true)}>
            Nouvel utilisateur
          </Button>
        }
      />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <Input
            size="sm"
            leftIcon={<Search aria-hidden />}
            placeholder="Nom ou e-mail…"
            value={search.value}
            onChange={(e) => search.setValue(e.target.value)}
            className="w-full sm:w-64"
            aria-label="Rechercher un utilisateur"
          />
          <SimpleSelect
            size="sm"
            className="w-40"
            aria-label="Rôle"
            value={role ?? ALL}
            options={[{ value: ALL, label: "Tous les rôles" }, ...ROLES.map((r) => ({ value: r, label: ROLE_META[r].label }))]}
            onValueChange={(v) => set({ role: v === ALL ? null : v, page: null })}
          />
          <SimpleSelect
            size="sm"
            className="w-36"
            aria-label="État"
            value={activeParam ?? ALL}
            options={[
              { value: ALL, label: "Tous" },
              { value: "true", label: "Actifs" },
              { value: "false", label: "Désactivés" },
            ]}
            onValueChange={(v) => set({ active: v === ALL ? null : v, page: null })}
          />
        </div>
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} variant="plain" />
        ) : query.isPending ? (
          <TableSkeleton />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Utilisateur</TableHead>
                <TableHead>Rôle</TableHead>
                <TableHead>Habilitation</TableHead>
                <TableHead>État</TableHead>
                <TableHead className="hidden md:table-cell">Dernière connexion</TableHead>
                <TableHead className="w-12">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.items.length === 0 ? (
                <TableEmptyRow colSpan={6}>Aucun utilisateur ne correspond.</TableEmptyRow>
              ) : (
                query.data.items.map((u) => (
                  <TableRow key={u.id} className={u.active ? undefined : "opacity-60"}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <UserAvatar user={u} size="sm" showName withEmail />
                        {u.id === me?.id ? <Badge tone="orange">Vous</Badge> : null}
                      </div>
                    </TableCell>
                    <TableCell>
                      <RoleBadge value={u.role} />
                    </TableCell>
                    <TableCell>
                      <ClassificationBadge level={u.clearance} />
                    </TableCell>
                    <TableCell>{u.active ? <Badge tone="green" dot>Actif</Badge> : <Badge tone="neutral" dot>Désactivé</Badge>}</TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground md:table-cell">
                      <RelativeTime date={u.last_login_at} fallback="Jamais" />
                    </TableCell>
                    <TableCell>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon-sm" aria-label={`Actions pour ${u.full_name}`}>
                            <MoreHorizontal aria-hidden />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onSelect={() => setEditing(u)}>
                            <Pencil aria-hidden /> Modifier rôle et habilitation
                          </DropdownMenuItem>
                          <DropdownMenuItem onSelect={() => setResetting(u)}>
                            <KeyRound aria-hidden /> Réinitialiser le mot de passe
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem onSelect={() => setToggling(u)} disabled={u.id === me?.id}>
                            {u.active ? <UserX aria-hidden /> : <UserCheck aria-hidden />}
                            {u.active ? "Désactiver" : "Réactiver"}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
        {query.data && query.data.total > PAGE_SIZE ? (
          <div className="border-t border-border p-3">
            <Pagination page={page} pageSize={PAGE_SIZE} total={query.data.total} onPageChange={(p) => set({ page: p > 1 ? p : null })} />
          </div>
        ) : null}
      </Card>

      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} />
      <EditUserDialog user={editing} onClose={() => setEditing(null)} isSelf={editing?.id === me?.id} />
      <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />
      <ConfirmDialog
        open={Boolean(toggling)}
        onOpenChange={(o) => !o && setToggling(null)}
        title={toggling?.active ? `Désactiver ${toggling.full_name} ?` : `Réactiver ${toggling?.full_name ?? ""} ?`}
        description={
          toggling?.active
            ? "Le compte ne pourra plus se connecter ; l'historique et l'audit sont conservés."
            : "Le compte pourra de nouveau se connecter avec son mot de passe."
        }
        confirmLabel={toggling?.active ? "Désactiver" : "Réactiver"}
        destructive={Boolean(toggling?.active)}
        onConfirm={async () => {
          if (!toggling) return;
          try {
            await update.mutateAsync({ id: toggling.id, body: { active: !toggling.active } });
            toast.success(toggling.active ? "Compte désactivé" : "Compte réactivé");
            setToggling(null);
          } catch (error) {
            toast.error(errorMessage(error));
          }
        }}
      />
    </section>
  );
}
