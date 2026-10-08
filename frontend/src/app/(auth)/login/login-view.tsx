"use client";

import * as React from "react";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Eye, EyeOff, Lock, Mail, UserPlus } from "lucide-react";

import { ForgeWordmark } from "@/components/brand/forge-logo";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useLogin, useMe } from "@/lib/api/auth";
import { formatRetryDelay, isApiError } from "@/lib/api/client";
import { cn, safeNextPath } from "@/lib/utils";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const LANG_KEY = "forge-login-lang";
const ACCESS_CONTACT = "yassine.aqejjaj@devoteam.com";

type Lang = "fr" | "en";

/** Sign-in page copy. The rest of FORGE is in French; this page is bilingual (EN/FR switch). */
const T = {
  fr: {
    headline: "Le moteur d’évaluation et d’apprentissage pour vos agents IA",
    lead: "Évaluez, améliorez et faites progresser des systèmes IA fiables.",
    signature: ["Tech for People.", "AI for Impact."],
    signIn: "Connexion",
    signUp: "Inscription",
    email: "E-mail professionnel",
    password: "Mot de passe",
    remember: "Rester connecté",
    submit: "Connexion",
    redirecting: "Redirection…",
    or: "ou continuer avec",
    soon: "Bientôt",
    googleSoon: "Connexion avec Google : bientôt disponible",
    show: "Afficher le mot de passe",
    hide: "Masquer le mot de passe",
    needLogin: "Connectez-vous pour accéder à la page demandée.",
    refused: "Connexion refusée",
    signUpTitle: "Accès sur invitation",
    signUpText:
      "Les comptes FORGE sont créés par un administrateur de votre organisation. Demandez un accès en indiquant votre rôle et les agents que vous souhaitez évaluer.",
    signUpCta: "Demander un accès",
    signUpSubject: "Demande d’accès à FORGE",
    language: "Langue",
    errors: {
      emailMissing: "Saisissez votre adresse e-mail.",
      emailInvalid: "Adresse e-mail invalide.",
      passwordMissing: "Saisissez votre mot de passe.",
      credentials: "E-mail ou mot de passe incorrect.",
      forbidden: "Ce compte n’est pas autorisé à se connecter.",
      rateLimited: (delay?: string) =>
        delay
          ? `Trop de tentatives de connexion. Réessayez dans ${delay}.`
          : "Trop de tentatives de connexion. Patientez quelques instants avant de réessayer.",
      unreachable: "Le service FORGE est injoignable pour le moment. Réessayez dans quelques instants.",
      generic: "Connexion impossible. Réessayez.",
    },
  },
  en: {
    headline: "The evaluation and learning engine for your AI agents",
    lead: "Evaluate, improve and grow reliable AI systems.",
    signature: ["Tech for People.", "AI for Impact."],
    signIn: "Sign in",
    signUp: "Sign up",
    email: "Work email",
    password: "Password",
    remember: "Stay signed in",
    submit: "Sign in",
    redirecting: "Redirecting…",
    or: "or continue with",
    soon: "Soon",
    googleSoon: "Sign in with Google: coming soon",
    show: "Show password",
    hide: "Hide password",
    needLogin: "Sign in to open the requested page.",
    refused: "Sign-in refused",
    signUpTitle: "Invitation only",
    signUpText:
      "FORGE accounts are created by an administrator of your organisation. Request access with your role and the agents you want to evaluate.",
    signUpCta: "Request access",
    signUpSubject: "FORGE access request",
    language: "Language",
    errors: {
      emailMissing: "Enter your email address.",
      emailInvalid: "Invalid email address.",
      passwordMissing: "Enter your password.",
      credentials: "Incorrect email or password.",
      forbidden: "This account is not allowed to sign in.",
      rateLimited: (delay?: string) =>
        delay ? `Too many sign-in attempts. Try again in ${delay}.` : "Too many sign-in attempts. Wait a moment and try again.",
      unreachable: "FORGE cannot be reached right now. Try again in a moment.",
      generic: "Sign-in failed. Try again.",
    },
  },
} as const;

type Copy = (typeof T)[Lang];

function loginErrorMessage(error: unknown, t: Copy): string {
  if (isApiError(error)) {
    if (error.status === 401 || error.status === 400) return t.errors.credentials;
    if (error.status === 403) return error.detail || t.errors.forbidden;
    if (error.status === 429) return t.errors.rateLimited(error.retryAfter ? formatRetryDelay(error.retryAfter) : undefined);
    if (error.isNetwork || error.isServer) return t.errors.unreachable;
    return error.detail;
  }
  return t.errors.generic;
}

function readLang(): Lang {
  try {
    return window.localStorage.getItem(LANG_KEY) === "en" ? "en" : "fr";
  } catch {
    return "fr";
  }
}

/** Official four-colour Google "G" (brand mark of the « continue with Google » button). */
function GoogleMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden>
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.6-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.6-.4-3.5z" />
    </svg>
  );
}

/** Brand panel: generated nebula, the crystal star, the forge wordmark and the promise. */
function CosmosPanel({ t }: { t: Copy }) {
  return (
    <aside className="relative hidden overflow-hidden bg-[#0b080c] text-white lg:flex lg:flex-col" aria-hidden>
      <Image src="/brand/login/cosmos.jpg" alt="" fill priority sizes="50vw" className="object-cover" />
      <div className="pointer-events-none absolute left-1/2 top-[40%] size-[70%] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(closest-side,rgb(255_92_120/0.45),rgb(214_38_170/0.18)_55%,transparent)]" />
      <div className="relative px-12 pt-12 xl:px-16 xl:pt-14">
        <ForgeWordmark height={64} tone="on-dark" label={null} />
      </div>
      <div className="relative flex flex-1 items-center justify-center">
        <Image
          src="/brand/login/crystal-star.png"
          alt=""
          width={740}
          height={760}
          priority
          sizes="(min-width: 1024px) 30vw, 0px"
          className="h-auto w-[min(58%,520px)] select-none motion-safe:animate-float drop-shadow-[0_0_60px_rgb(255_120_150/0.55)]"
        />
      </div>
      <div className="relative flex items-end justify-between gap-8 px-12 pb-12 xl:px-16 xl:pb-14">
        <div className="max-w-xl">
          <p className="text-balance text-[34px] font-semibold leading-[1.12] tracking-tight xl:text-[42px]">{t.headline}</p>
          <p className="mt-4 max-w-md text-[17px] leading-relaxed text-white/85 xl:text-lg">{t.lead}</p>
        </div>
        <p className="shrink-0 text-right text-[13px] leading-relaxed text-white/80">
          {t.signature[0]}
          <br />
          {t.signature[1]}
        </p>
      </div>
    </aside>
  );
}

export function LoginView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawNext = searchParams.get("next");
  const next = safeNextPath(rawNext);

  const [lang, setLang] = React.useState<Lang>("fr");
  const t = T[lang];
  React.useEffect(() => setLang(readLang()), []);
  React.useEffect(() => {
    const previous = { lang: document.documentElement.lang, title: document.title };
    document.documentElement.lang = lang;
    document.title = lang === "en" ? "Sign in · FORGE" : "Connexion · FORGE";
    return () => {
      document.documentElement.lang = previous.lang;
      document.title = previous.title;
    };
  }, [lang]);
  const chooseLang = (value: Lang) => {
    setLang(value);
    try {
      window.localStorage.setItem(LANG_KEY, value);
    } catch {
      // storage unavailable: the choice lasts for this page only
    }
  };

  const [tab, setTab] = React.useState<"signin" | "signup">("signin");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [remember, setRemember] = React.useState(true);
  const [showPassword, setShowPassword] = React.useState(false);
  const [fieldErrors, setFieldErrors] = React.useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = React.useState<string | null>(null);
  const [redirecting, setRedirecting] = React.useState(false);

  const emailRef = React.useRef<HTMLInputElement>(null);
  const passwordRef = React.useRef<HTMLInputElement>(null);

  // Already signed in? Go straight to the destination.
  const me = useMe({ redirectOnUnauthorized: false, staleTime: 0 });
  React.useEffect(() => {
    if (me.isSuccess) {
      setRedirecting(true);
      router.replace(next);
    }
  }, [me.isSuccess, next, router]);

  const login = useLogin();

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);
    const errors: { email?: string; password?: string } = {};
    const trimmed = email.trim();
    if (!trimmed) errors.email = t.errors.emailMissing;
    else if (!EMAIL_RE.test(trimmed)) errors.email = t.errors.emailInvalid;
    if (!password) errors.password = t.errors.passwordMissing;
    setFieldErrors(errors);
    if (errors.email) {
      emailRef.current?.focus();
      return;
    }
    if (errors.password) {
      passwordRef.current?.focus();
      return;
    }

    try {
      await login.mutateAsync({ email: trimmed, password, remember });
      setRedirecting(true);
      router.replace(next);
    } catch (error) {
      setFormError(loginErrorMessage(error, t));
      setPassword("");
      passwordRef.current?.focus();
    }
  };

  const busy = login.isPending || redirecting;
  const tabClass = (active: boolean) =>
    cn(
      "-mb-px flex-1 border-b-2 pb-3 text-[15px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
      active ? "border-primary text-brand" : "border-transparent text-muted-foreground hover:text-foreground",
    );

  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      <CosmosPanel t={t} />

      <main className="relative flex flex-col bg-background">
        <div className="flex justify-end px-5 pt-5 sm:px-8 sm:pt-6">
          <div role="group" aria-label={t.language} className="inline-flex rounded-full border border-border bg-card p-1 shadow-panel">
            {(["en", "fr"] as const).map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => chooseLang(l)}
                aria-pressed={lang === l}
                lang={l}
                className={cn(
                  "h-8 min-w-11 rounded-full px-3 text-[13px] font-semibold uppercase transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                  lang === l ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {l}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-8">
          <div className="w-full max-w-[520px] rounded-2xl border border-border bg-card px-6 py-9 shadow-panel sm:px-12 sm:py-12">
            <h1 className="flex justify-center">
              <ForgeWordmark height={68} label="FORGE" />
            </h1>

            <div role="tablist" aria-label="FORGE" className="mt-8 flex border-b border-border">
              <button
                type="button"
                role="tab"
                id="tab-signin"
                aria-selected={tab === "signin"}
                aria-controls="panel-signin"
                className={tabClass(tab === "signin")}
                onClick={() => setTab("signin")}
              >
                {t.signIn}
              </button>
              <button
                type="button"
                role="tab"
                id="tab-signup"
                aria-selected={tab === "signup"}
                aria-controls="panel-signup"
                className={tabClass(tab === "signup")}
                onClick={() => setTab("signup")}
              >
                {t.signUp}
              </button>
            </div>

            {tab === "signin" ? (
              <div role="tabpanel" id="panel-signin" aria-labelledby="tab-signin">
                {rawNext && !formError ? (
                  <Alert tone="blue" className="mt-6" icon={<Lock aria-hidden />}>
                    {t.needLogin}
                  </Alert>
                ) : null}
                {formError ? (
                  <Alert id="login-error" tone="red" className="mt-6" title={t.refused}>
                    {formError}
                  </Alert>
                ) : null}

                <form onSubmit={submit} noValidate className="mt-7 grid gap-5" aria-describedby={formError ? "login-error" : undefined}>
                  <Field id="login-email" label={t.email} error={fieldErrors.email}>
                    <Input
                      ref={emailRef}
                      id="login-email"
                      name="email"
                      type="email"
                      inputMode="email"
                      autoComplete="username"
                      autoCapitalize="none"
                      spellCheck={false}
                      autoFocus
                      size="lg"
                      placeholder="prenom.nom@devoteam.com"
                      leftIcon={<Mail aria-hidden />}
                      value={email}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        if (fieldErrors.email) setFieldErrors((p) => ({ ...p, email: undefined }));
                      }}
                      invalid={Boolean(fieldErrors.email)}
                      aria-describedby={fieldDescribedBy("login-email", { error: fieldErrors.email })}
                      disabled={busy}
                      required
                    />
                  </Field>

                  <Field id="login-password" label={t.password} error={fieldErrors.password}>
                    <Input
                      ref={passwordRef}
                      id="login-password"
                      name="password"
                      type={showPassword ? "text" : "password"}
                      autoComplete="current-password"
                      size="lg"
                      placeholder="••••••••••"
                      leftIcon={<Lock aria-hidden />}
                      value={password}
                      onChange={(e) => {
                        setPassword(e.target.value);
                        if (fieldErrors.password) setFieldErrors((p) => ({ ...p, password: undefined }));
                      }}
                      invalid={Boolean(fieldErrors.password)}
                      aria-describedby={fieldDescribedBy("login-password", { error: fieldErrors.password })}
                      disabled={busy}
                      required
                      rightSlot={
                        <button
                          type="button"
                          onClick={() => setShowPassword((s) => !s)}
                          className="flex size-7 items-center justify-center rounded-md text-subtle-foreground transition-colors hover:bg-surface-3 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                          aria-label={showPassword ? t.hide : t.show}
                          aria-pressed={showPassword}
                        >
                          {showPassword ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
                        </button>
                      }
                    />
                  </Field>

                  <label htmlFor="login-remember" className="flex w-fit cursor-pointer items-center gap-2.5 text-sm text-foreground">
                    <Checkbox
                      id="login-remember"
                      checked={remember}
                      onCheckedChange={(v) => setRemember(v === true)}
                      disabled={busy}
                    />
                    {t.remember}
                  </label>

                  <Button type="submit" size="lg" className="w-full" loading={busy} rightIcon={!busy ? <ArrowRight aria-hidden /> : undefined}>
                    {redirecting ? t.redirecting : t.submit}
                  </Button>
                </form>

                <div className="my-6 flex items-center gap-3 text-[13px] text-subtle-foreground" aria-hidden>
                  <span className="h-px flex-1 bg-border" />
                  {t.or}
                  <span className="h-px flex-1 bg-border" />
                </div>

                <button
                  type="button"
                  disabled
                  aria-label={t.googleSoon}
                  className="relative flex h-12 w-full cursor-not-allowed items-center justify-center gap-3 rounded-lg border border-border-strong bg-card text-[15px] font-semibold text-foreground"
                >
                  <GoogleMark className="size-5" />
                  Google
                  <span className="absolute right-3 rounded-md bg-sky-500/12 px-2 py-0.5 text-[12px] font-medium text-sky-700 dark:text-sky-300">
                    {t.soon}
                  </span>
                </button>
              </div>
            ) : (
              <div role="tabpanel" id="panel-signup" aria-labelledby="tab-signup" className="mt-7 grid gap-4">
                <span className="flex size-11 items-center justify-center rounded-xl bg-brand-soft text-brand" aria-hidden>
                  <UserPlus className="size-5" />
                </span>
                <h2 className="text-lg font-semibold tracking-tight">{t.signUpTitle}</h2>
                <p className="text-sm leading-relaxed text-muted-foreground">{t.signUpText}</p>
                <Button asChild size="lg" variant="secondary" className="mt-2 w-full">
                  <a href={`mailto:${ACCESS_CONTACT}?subject=${encodeURIComponent(t.signUpSubject)}`}>{t.signUpCta}</a>
                </Button>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
