"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { SETTINGS_NAV } from "@/components/layout/nav";
import { Spinner } from "@/components/ui/spinner";
import { useCurrentUser } from "@/hooks/use-current-user";

/** /settings → first section the user may open. */
export default function SettingsIndexPage() {
  const router = useRouter();
  const { hasRole, isLoading } = useCurrentUser();
  const first = SETTINGS_NAV.find((t) => !t.minRole || hasRole(t.minRole));

  React.useEffect(() => {
    if (!isLoading && first) router.replace(first.href);
  }, [first, isLoading, router]);

  return (
    <div className="flex justify-center py-12">
      <Spinner />
    </div>
  );
}
