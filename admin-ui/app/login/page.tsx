/**
 * Login page — single Keycloak sign-in button. Sasai brand colours.
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
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-md rounded-2xl border bg-card p-8 shadow-xl">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
            <Building2 className="h-4 w-4 text-primary-foreground" />
          </div>
          <div>
            <h1 className="text-lg font-semibold leading-tight text-foreground">
              Sasai Wallet
            </h1>
            <p className="text-xs text-muted-foreground">Admin Console</p>
          </div>
        </div>
        <p className="mb-6 text-sm text-muted-foreground">
          Sign in with your Sasai operator account. Authentication runs through
          the platform's Keycloak realm — your roles determine what you can see
          and do here.
        </p>
        {reason === "refresh_failed" && (
          <div className="mb-4 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
            Your session expired and could not be refreshed. Please sign in again.
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
        <div className="mt-6 text-center text-[11px] text-muted-foreground">
          Local dev creates a default <code className="text-foreground">admin-test</code> user.
          See <code className="text-foreground">sasai-wallet-infra/.claude.md</code>.
        </div>
      </div>
    </div>
  );
}
