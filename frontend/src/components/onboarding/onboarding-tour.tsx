"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Check, Command, Rocket } from "lucide-react";

import { ClassificationBadge } from "@/components/domain/classification-badge";
import { RoleBadge } from "@/components/domain/enum-badge";
import { useShell } from "@/components/layout/shell-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useCompleteOnboarding } from "@/lib/api/auth";
import { cn } from "@/lib/utils";

import { JOURNEY, ROLE_SUMMARY, firstActions } from "./steps";

const STEP_COUNT = 4;

function firstName(fullName: string | undefined, email: string | undefined): string {
  const name = fullName?.trim().split(/\s+/)[0];
  return name || email?.split("@")[0] || "";
}

/**
 * Welcome tour. Opens by itself on the first login of an account (`onboarded_at === null`) and on demand
 * from the user menu. Closing it in any way (end, « Passer », Échap, a first-step link) stamps the account
 * as onboarded, so it never reappears on its own.
 */
export function OnboardingTour() {
  const { user, role } = useCurrentUser();
  const { onboardingReplayOpen, setOnboardingReplayOpen } = useShell();
  const complete = useCompleteOnboarding();
  const [step, setStep] = React.useState(0);
  // Keeps the tour closed for the rest of the session even if the completion call fails.
  const [dismissed, setDismissed] = React.useState(false);

  const firstRun = user?.onboarded_at === null && !dismissed;
  const open = firstRun || onboardingReplayOpen;

  const finish = React.useCallback(() => {
    setDismissed(true);
    setOnboardingReplayOpen(false);
    if (user?.onboarded_at === null) complete.mutate();
  }, [complete, setOnboardingReplayOpen, user?.onboarded_at]);

  // Every opening starts at the first step.
  React.useEffect(() => {
    if (open) setStep(0);
  }, [open]);

  if (!user) return null;
  const last = step === STEP_COUNT - 1;
  const actions = firstActions(role);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && finish()}>
      <DialogContent size="md" className="gap-5">
        {step === 0 ? (
          <DialogHeader>
            <DialogTitle className="text-xl">Bienvenue sur FORGE, {firstName(user.full_name, user.email)}</DialogTitle>
            <DialogDescription>
              FORGE répond à une question : « Est-ce que cette nouvelle version de mon agent est réellement meilleure ? »
              — de façon mesurable, sur quels scénarios, à quel coût, avec quelles erreurs.
            </DialogDescription>
          </DialogHeader>
        ) : (
          <DialogHeader>
            <DialogTitle>
              {step === 1 ? "La boucle FORGE en quatre temps" : step === 2 ? "Pour bien démarrer" : "Vous êtes prêt"}
            </DialogTitle>
            <DialogDescription>
              {step === 1
                ? "Le menu de gauche suit ce parcours, de haut en bas."
                : step === 2
                  ? "Quelques points d'entrée adaptés à votre rôle."
                  : "Deux repères à garder en tête."}
            </DialogDescription>
          </DialogHeader>
        )}

        {step === 0 ? (
          <div className="grid gap-3 rounded-xl border border-border bg-surface-2 p-4">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">Votre rôle</span>
              {role ? <RoleBadge value={role} withTooltip={false} /> : null}
              <ClassificationBadge level={user.clearance} prefix="Habilitation" showLabel={false} noTooltip />
            </div>
            {role ? <p className="text-sm text-muted-foreground">{ROLE_SUMMARY[role]}</p> : null}
            <p className="text-xs text-muted-foreground">
              L&apos;habilitation (C0 à C3) fixe le niveau de classification des scénarios que vous pouvez voir.
              Un administrateur peut ajuster votre rôle et votre habilitation.
            </p>
          </div>
        ) : null}

        {step === 1 ? (
          <ol className="grid gap-2.5">
            {JOURNEY.map((stage, i) => (
              <li key={stage.id} className="flex items-start gap-3 rounded-xl border border-border p-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-brand">
                  <stage.icon className="size-4" aria-hidden />
                </span>
                <div className="grid gap-0.5">
                  <p className="text-sm font-medium">
                    <span className="text-muted-foreground">{i + 1}.</span> {stage.label}
                  </p>
                  <p className="text-[13px] leading-relaxed text-muted-foreground">{stage.text}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : null}

        {step === 2 ? (
          <ul className="grid gap-2">
            {actions.map((action) => (
              <li key={action.href}>
                <Link
                  href={action.href}
                  onClick={finish}
                  className="group flex items-center gap-3 rounded-xl border border-border p-3 transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-brand">
                    <action.icon className="size-4" aria-hidden />
                  </span>
                  <span className="grid min-w-0 flex-1 gap-0.5">
                    <span className="text-sm font-medium">{action.label}</span>
                    <span className="text-[13px] text-muted-foreground">{action.text}</span>
                  </span>
                  <ArrowRight
                    className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
                    aria-hidden
                  />
                </Link>
              </li>
            ))}
          </ul>
        ) : null}

        {last ? (
          <div className="grid gap-3 text-sm">
            <div className="flex items-start gap-3 rounded-xl border border-border p-3">
              <Command className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
              <p className="leading-relaxed text-muted-foreground">
                <span className="font-medium text-foreground">Aller n&apos;importe où :</span> <Kbd>⌘</Kbd> <Kbd>K</Kbd>{" "}
                (ou <Kbd>Ctrl</Kbd> <Kbd>K</Kbd>) ouvre la recherche de pages et d&apos;actions.
              </p>
            </div>
            <div className="flex items-start gap-3 rounded-xl border border-border p-3">
              <Rocket className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
              <p className="leading-relaxed text-muted-foreground">
                <span className="font-medium text-foreground">Revoir cette visite :</span> menu de votre avatar en haut à
                droite, entrée « Visite guidée ».
              </p>
            </div>
          </div>
        ) : null}

        <DialogFooter className="items-center sm:justify-between">
          <div className="flex items-center gap-1.5" role="group" aria-label={`Étape ${step + 1} sur ${STEP_COUNT}`}>
            {Array.from({ length: STEP_COUNT }, (_, i) => (
              <span
                key={i}
                aria-hidden
                className={cn("h-1.5 rounded-full transition-all", i === step ? "w-5 bg-brand" : "w-1.5 bg-border-strong")}
              />
            ))}
          </div>
          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            {!last ? (
              <Button variant="ghost" onClick={finish}>
                Passer
              </Button>
            ) : null}
            {step > 0 ? (
              <Button variant="secondary" onClick={() => setStep((s) => s - 1)}>
                Précédent
              </Button>
            ) : null}
            {last ? (
              <Button onClick={finish} leftIcon={<Check aria-hidden />}>
                C&apos;est parti
              </Button>
            ) : (
              <Button onClick={() => setStep((s) => s + 1)} rightIcon={<ArrowRight aria-hidden />}>
                Suivant
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
