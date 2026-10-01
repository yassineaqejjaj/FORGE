import { ForgeMark } from "@/components/brand/forge-logo";

/** Full-screen loading state (session check, redirects). */
export function SplashScreen({ label = "Chargement de FORGE…" }: { label?: string }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-background" role="status" aria-live="polite">
      <div className="relative">
        <span className="absolute inset-0 animate-ping rounded-xl bg-brand/20" aria-hidden />
        <ForgeMark width={44} height={44} className="relative" animated />
      </div>
      <p className="text-[13px] text-muted-foreground">{label}</p>
    </div>
  );
}
