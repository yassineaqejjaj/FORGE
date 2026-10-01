import Link from "next/link";
import { ArrowLeft, LayoutDashboard } from "lucide-react";

import { ForgeMark } from "@/components/brand/forge-logo";
import { Button } from "@/components/ui/button";

export const metadata = { title: "Page introuvable" };

export default function NotFound() {
  return (
    <main className="relative flex min-h-dvh flex-col items-center justify-center overflow-hidden bg-background px-4 text-center">
      <div
        className="bg-grid pointer-events-none absolute inset-0 [mask-image:radial-gradient(ellipse_at_center,black_20%,transparent_70%)]"
        aria-hidden
      />
      <div className="relative grid max-w-md justify-items-center gap-5">
        <ForgeMark width={48} height={48} />
        <p className="font-mono text-sm font-medium tracking-widest text-brand">ERREUR 404</p>
        <h1 className="text-2xl font-semibold tracking-tight">Cette page n&apos;est jamais sortie de la forge</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          La page demandée n&apos;existe pas, a été déplacée ou vous n&apos;y avez pas accès.
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <Button asChild>
            <Link href="/">
              <LayoutDashboard aria-hidden />
              Tableau de bord
            </Link>
          </Button>
          <Button asChild variant="secondary">
            <Link href="/login">
              <ArrowLeft aria-hidden />
              Connexion
            </Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
