import { ForgeWordmark } from "@/components/brand/forge-logo";

/** Full-screen loading state (session check, redirects). */
export function SplashScreen({ label = "Chargement de FORGE…" }: { label?: string }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-background" role="status" aria-live="polite">
      <ForgeWordmark height={40} animated label={null} />
      <p className="text-[13px] text-muted-foreground">{label}</p>
    </div>
  );
}
