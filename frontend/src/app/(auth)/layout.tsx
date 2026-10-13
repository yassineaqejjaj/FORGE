import { authFont } from "@/lib/fonts";

/** Unauthenticated routes (login): no app shell, brand typography (Montserrat, self-hosted). */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className={`min-h-dvh bg-background ${authFont.className}`}>{children}</div>;
}
