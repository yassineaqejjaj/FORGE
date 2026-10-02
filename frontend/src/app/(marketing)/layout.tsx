import { Montserrat } from "next/font/google";

/** Public marketing pages: no application shell, no authentication, Devoteam typography. */
const montserrat = Montserrat({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700", "800"],
  display: "swap",
  variable: "--font-landing",
});

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div lang="en" className={montserrat.variable}>
      {children}
    </div>
  );
}
