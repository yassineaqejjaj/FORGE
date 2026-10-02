import type { Metadata } from "next";

import { LandingPage } from "@/components/landing/landing-page";

export const metadata: Metadata = {
  title: { absolute: "Devoteam | Forge — Agent evaluation platform" },
  description:
    "Forge tests, governs and improves your AI agents on every release: scenarios, LLM and human judges, release gates, audit trail.",
  robots: { index: true, follow: true },
  openGraph: {
    title: "Devoteam | Forge",
    description: "Know your AI agents work before your customers do.",
    images: [{ url: "/landing/devoteam-forge.png", width: 954, height: 180, alt: "Devoteam | Forge" }],
    type: "website",
  },
};

export default function HomePage() {
  return <LandingPage />;
}
