import { landingFont } from "@/lib/fonts";

/** Public marketing pages: no application shell, no authentication, Devoteam typography. */

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div lang="en" className={landingFont.variable}>
      {children}
    </div>
  );
}
