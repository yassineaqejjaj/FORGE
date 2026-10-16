import type { Metadata } from "next";

import { LinkView } from "./link-view";

export const metadata: Metadata = { title: "Lier ce compte" };

export default function OidcLinkPage() {
  return <LinkView />;
}
