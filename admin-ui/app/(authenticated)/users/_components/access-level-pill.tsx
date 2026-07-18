/**
 * <AccessLevelPill> — small pill shown in the user hero when an admin has
 * imposed an access restriction. `login_locked` → red "Login locked";
 * `transactions_locked` → amber "Transactions locked". `active`/`closed`
 * render nothing (the status pill already conveys `closed`). Distinct from
 * the automatic PIN-lockout <LockoutBadge>. Server component.
 */
import { Ban, ShieldOff } from "lucide-react";

import type { AccessLevel } from "@/lib/api-types";

export function AccessLevelPill({ level }: { level: AccessLevel }) {
  if (level === "login_locked") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-100">
        <Ban className="h-3 w-3" aria-hidden="true" />
        Login locked
      </span>
    );
  }
  if (level === "transactions_locked") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-amber-500/20 px-2 py-0.5 text-xs font-medium text-amber-100">
        <ShieldOff className="h-3 w-3" aria-hidden="true" />
        Transactions locked
      </span>
    );
  }
  return null;
}
