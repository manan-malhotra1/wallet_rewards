/**
 * Client form for the in-app credentials login. Lives next to
 * `app/login/page.tsx` and is rendered inside the brand chrome there.
 *
 * Uses React 19's `useActionState` so we can surface inline validation
 * errors from the `loginAction` server action without a client-side fetch
 * to /api/auth/callback/credentials. Pending state disables the submit
 * button while the password grant round-trips to Keycloak.
 */
"use client";

import { AlertCircle } from "lucide-react";
import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { loginAction, type LoginActionState } from "./actions";

const initialState: LoginActionState = { error: null };

/**
 * Email + password form. The `from` query param is round-tripped through
 * a hidden input so the server action can redirect back to the originally
 * requested page after sign-in.
 */
export function LoginForm({ from }: { from: string }) {
  const [state, formAction, pending] = useActionState(loginAction, initialState);
  return (
    <form action={formAction} className="space-y-4" noValidate>
      <input type="hidden" name="from" value={from} />
      <div className="space-y-1.5">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          autoFocus
          required
          aria-invalid={state.error ? true : undefined}
          placeholder="operator@sasaifintech.com"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          aria-invalid={state.error ? true : undefined}
        />
      </div>
      {state.error && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive"
        >
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>{state.error}</span>
        </div>
      )}
      <Button type="submit" size="lg" className="w-full" disabled={pending}>
        {pending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
