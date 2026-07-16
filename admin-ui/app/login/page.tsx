/**
 * Login page — in-app credentials form (email + password). The Keycloak
 * password grant runs server-side inside the credentials provider's
 * `authorize()` callback in `auth.ts`; this page just renders the brand
 * chrome (Sasai navy field + watermark) and embeds <LoginForm/>.
 */
import { SasaiLogo } from "@/components/branding/sasai-logo";

import { LoginForm } from "./login-form";

export const dynamic = "force-dynamic";

/** Sasai brand navy (matches sasai.global). */
const SASAI_NAVY = "#144989";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; reason?: string }>;
}) {
  const { from = "/dashboard", reason } = await searchParams;
  return (
    <div
      className="relative flex min-h-screen items-center justify-center overflow-hidden p-6"
      style={{ backgroundColor: SASAI_NAVY }}
    >
      {/* Faint Sasai watermark on the navy field (logo forced to white). */}
      <img
        src="/sasai-logo.png"
        alt=""
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 select-none opacity-[0.06]"
        style={{ width: "min(85vw, 820px)", filter: "brightness(0) invert(1)" }}
      />
      <div className="relative z-10 w-full max-w-md rounded-2xl border bg-card p-8 shadow-xl">
        <div className="mb-6 flex items-center justify-between gap-3">
          <SasaiLogo height={32} />
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
