/**
 * Login page — in-app credentials form (email + password). The Keycloak
 * password grant runs server-side inside the credentials provider's
 * `authorize()` callback in `auth.ts`; this page just renders the brand
 * chrome (frosted logo card over the body's tenant-branded atmosphere) and
 * embeds <LoginForm/>.
 */
import { SasaiLogo } from "@/components/branding/sasai-logo";

import { LoginForm } from "./login-form";

export const dynamic = "force-dynamic";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; reason?: string }>;
}) {
  const { from = "/dashboard", reason } = await searchParams;
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="glass-panel w-full max-w-md rounded-2xl p-8">
        {/* Sasai brand mark at the top of the modal (on the frosted card). */}
        <div className="mb-6 flex flex-col items-center gap-3">
          <SasaiLogo height={36} />
          <span className="rounded-full border bg-muted/50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Admin Console
          </span>
        </div>
        {reason === "refresh_failed" && (
          <div className="mb-4 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
            Your session expired and could not be refreshed. Please sign in
            again.
          </div>
        )}
        <LoginForm from={from} />
        <div className="mt-6 text-center text-[11px] text-muted-foreground">
          Local dev seeds <code className="text-foreground">admin-test@example.test</code>{" "}
          with password <code className="text-foreground">admin-test-pass</code>.
        </div>
      </div>
    </div>
  );
}
