import localFont from "next/font/local";

// Self-hosted variable font (latin subset, OFL; same file as NOVA): the build never reaches
// fonts.googleapis.com. One variable file covers weights 100-900, so 300 to 800 are all available.
// next/font needs literal ``src`` strings (static analysis): the path is repeated on purpose.

/** Public marketing pages (Devoteam typography); exposed as the ``--font-landing`` CSS variable. */
export const landingFont = localFont({
  src: "../assets/fonts/montserrat-latin-wght-normal.woff2",
  weight: "100 900",
  display: "swap",
  variable: "--font-landing",
});

/** Brand pages (login): applied through ``className``; the app itself keeps Geist. */
export const authFont = localFont({
  src: "../assets/fonts/montserrat-latin-wght-normal.woff2",
  weight: "100 900",
  display: "swap",
});
