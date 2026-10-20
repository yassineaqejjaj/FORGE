"use client";

/**
 * « Lier ce compte » (ADR 001 §8, NOV-108): shown after a first SSO sign-in whose verified e-mail matches an
 * existing FORGE account. Nothing is linked until the user confirms explicitly and proves the local account
 * with its password. Only reachable through the API redirect (the SSO routes exist only when OIDC is enabled).
 */
import * as React from "react";
import { useRouter } from "next/navigation";
import { Link2, Lock } from "lucide-react";

import { ForgeWordmark } from "@/components/brand/forge-logo";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { http, isApiError } from "@/lib/api/client";

interface PendingLink {
  account_email: string;
  account_name: string;
  idp_email: string | null;
  idp_name: string | null;
  issuer: string;
}

export function LinkView() {
  const router = useRouter();
  const [pending, setPending] = React.useState<PendingLink | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    http
      .get<PendingLink>("/auth/oidc/link", { redirectOnUnauthorized: false })
      .then(setPending)
      .catch(() => setLoadError("Aucune liaison en attente ou session expirée : reconnectez-vous par SSO."));
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!confirm) {
      setError("Cochez la case pour confirmer la liaison.");
      return;
    }
    setBusy(true);
    try {
      await http.post("/auth/oidc/link", { confirm: true, password }, { redirectOnUnauthorized: false });
      router.replace("/");
    } catch (e) {
      setError(isApiError(e) ? e.detail : "Liaison impossible. Réessayez.");
      setPassword("");
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-dvh items-center justify-center px-5 py-10">
      <div className="w-full max-w-[520px] rounded-2xl border border-border bg-card px-6 py-9 shadow-panel sm:px-12 sm:py-12">
        <h1 className="flex justify-center">
          <ForgeWordmark height={56} label="FORGE" />
        </h1>
        <h2 className="mt-8 flex items-center gap-2 text-lg font-semibold tracking-tight">
          <Link2 className="size-5" aria-hidden /> Lier ce compte
        </h2>
        {loadError ? (
          <Alert tone="red" className="mt-6">
            {loadError}
          </Alert>
        ) : pending ? (
          <form onSubmit={submit} noValidate className="mt-6 grid gap-5">
            <p className="text-sm leading-relaxed text-muted-foreground">
              Votre identité SSO ({pending.idp_email ?? "adresse non communiquée"}) correspond au compte FORGE{" "}
              <strong>{pending.account_email}</strong>. Rien n’est lié tant que vous ne confirmez pas : saisissez le
              mot de passe de ce compte FORGE pour prouver qu’il est bien le vôtre.
            </p>
            {error ? (
              <Alert tone="red" title="Liaison refusée">
                {error}
              </Alert>
            ) : null}
            <Field id="link-password" label="Mot de passe du compte FORGE">
              <Input
                id="link-password"
                type="password"
                autoComplete="current-password"
                size="lg"
                leftIcon={<Lock aria-hidden />}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={busy}
                required
              />
            </Field>
            <label htmlFor="link-confirm" className="flex cursor-pointer items-start gap-2.5 text-sm text-foreground">
              <Checkbox id="link-confirm" checked={confirm} onCheckedChange={(v) => setConfirm(v === true)} disabled={busy} />
              Je confirme lier mon compte FORGE à cette identité SSO.
            </label>
            <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!password}>
              Lier ce compte
            </Button>
          </form>
        ) : null}
      </div>
    </main>
  );
}
