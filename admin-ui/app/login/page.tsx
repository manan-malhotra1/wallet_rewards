/**
 * Login page. Single button — delegates to Keycloak via next-auth signIn().
 *
 * Public route — the middleware whitelists `/login` so unauthenticated
 * browsers can reach it. After successful sign-in we redirect back to
 * `?from=…` if provided, otherwise `/dashboard`.
 */
import { Building2, KeyRound } from "lucide-react";

import { signIn } from "@/auth";
import { Button } from "@/components/ui/button";

export const dynamic = "force-dynamic";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; reason?: string }>;
}) {
  const { from = "/dashboard", reason } = await searchParams;
  return (
    <div className="flex min-h-screen items-center justify-center bg-[--color-surface-0] p-6">
      <div className="w-full max-w-md rounded-xl border border-[--color-border] bg-[--color-surface-1] p-8 shadow-2xl">
        <div className="mb-6 flex items-center gap-2">
          <Building2 className="h-5 w-5 text-[--color-brand]" />
          <h1 className="text-[18px] font-semibold">Sasai Wallet · Admin</h1>
        </div>
        <p className="mb-6 text-[13px] text-[--color-text-2]">
          Sign in with your Sasai operator account. Authentication is handled
          by the platform's Keycloak realm — your roles determine what you
          can see and do here.
        </p>
        {reason === "refresh_failed" && (
          <div className="mb-4 rounded border border-[--color-warning]/40 bg-[--color-warning]/10 p-3 text-[12px] text-[--color-warning]">
            Your session expired and could not be refreshed. Please sign in
            again.
          </div>
        )}
        <form
          action={async () => {
            "use server";
            await signIn("keycloak", { redirectTo: from });
          }}
        >
          <Button type="submit" size="lg" className="w-full">
            <KeyRound className="h-4 w-4" />
            Sign in with Keycloak
          </Button>
        </form>
        <div className="mt-6 text-center text-[11px] text-[--color-text-3]">
          For local dev, the bootstrap script creates a default admin user.
          See <code className="text-[--color-text-2]">sasai-wallet-infra/.claude.md</code>.
        </div>
      </div>
    </div>
  );
}
