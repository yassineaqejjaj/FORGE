import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

import { Providers } from "@/components/providers/providers";
import { themeInitScript } from "@/lib/theme-script";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "FORGE — Laboratoire d'évaluation des agents IA",
    template: "%s · FORGE",
  },
  description:
    "FORGE répond à une question : cette nouvelle version de mon agent est-elle réellement meilleure ? Scénarios, critères, coûts, erreurs, régressions et niveau de confiance.",
  applicationName: "FORGE",
  authors: [{ name: "Devoteam — Programme NOVA" }],
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0e0b09" },
  ],
  colorScheme: "light dark",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-dvh bg-background font-sans text-foreground antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
