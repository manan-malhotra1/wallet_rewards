/**
 * <AuthControl> — per-user login/logout control shown in a WalletPane header.
 *
 * When logged out: a PIN input + "Log in" button (wrong PIN / lockout surfaced
 * inline). When logged in: a "Logged in ✓" badge + "Log out" button. The PIN
 * lives only in this component's transient state and reaches the backend via
 * the loginAction server action — the browser never stores it.
 */
"use client";

import { CheckCircle2, KeyRound, LogOut } from "lucide-react";
import * as React from "react";
import { useFormStatus } from "react-dom";

import { loginAction, logoutAction } from "@/app/_actions";
import type { UserKey } from "@/lib/config";

/** Submit button that reflects the in-flight state of its enclosing form. */
function SubmitButton({ idle, busy }: { idle: string; busy: string }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="flex items-center justify-center gap-1.5 rounded-md bg-[var(--color-brand)] px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:opacity-90 disabled:opacity-50"
    >
      {pending ? busy : idle}
    </button>
  );
}

export function AuthControl({
  user,
  loggedIn,
}: {
  user: UserKey;
  loggedIn: boolean;
}) {
  const [pin, setPin] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  async function doLogin() {
    const result = await loginAction(user, pin);
    setError(result.ok ? null : (result.message ?? "Login failed."));
    if (result.ok) setPin("");
  }

  async function doLogout() {
    await logoutAction(user);
    setError(null);
  }

  if (loggedIn) {
    return (
      <form action={doLogout} className="flex items-center gap-2">
        <span className="flex items-center gap-1 text-[11px] font-semibold text-[var(--color-success)]">
          <CheckCircle2 className="h-3.5 w-3.5" /> Logged in
        </span>
        <button
          type="submit"
          className="flex items-center gap-1 rounded-md border border-[var(--color-border)] px-2 py-1 text-[11px] font-medium text-[var(--color-fg-muted)] transition hover:bg-[var(--color-bg)]"
        >
          <LogOut className="h-3.5 w-3.5" /> Log out
        </button>
      </form>
    );
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <form action={doLogin} className="flex items-center gap-1.5">
        <KeyRound className="h-3.5 w-3.5 text-[var(--color-brand)]" />
        <input
          type="password"
          inputMode="numeric"
          autoComplete="off"
          value={pin}
          onChange={(e) => setPin(e.target.value)}
          placeholder="PIN"
          maxLength={4}
          aria-label={`${user} PIN`}
          className="w-20 rounded-md border border-[var(--color-border)] bg-white px-2 py-1 text-sm tabular-nums tracking-widest"
        />
        <SubmitButton idle="Log in" busy="…" />
      </form>
      {error ? (
        <div className="text-[11px] text-[var(--color-danger)]">{error}</div>
      ) : null}
    </div>
  );
}
