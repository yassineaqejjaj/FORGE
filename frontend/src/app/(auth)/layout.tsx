import { Montserrat } from "next/font/google";

/** Brand pages use Montserrat (design system); the app keeps Geist. */
const montserrat = Montserrat({ subsets: ["latin"], weight: ["400", "500", "600", "700"], display: "swap" });

/** Unauthenticated routes (login): no app shell. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className={`min-h-dvh bg-background ${montserrat.className}`}>{children}</div>;
}
