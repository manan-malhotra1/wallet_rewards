/**
 * Login page — in-app credentials form (email + password). The Keycloak
 * password grant runs server-side inside the credentials provider's
 * `authorize()` callback in `auth.ts`; this page just renders the brand
 * chrome (Sasai navy field + top logo) and embeds <LoginForm/>.
 */
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
      className="flex min-h-screen flex-col items-center justify-center gap-8 p-6"
      style={{ backgroundColor: SASAI_NAVY }}
    >
      {/* Sasai brand mark at the top of the login modal (logo forced white). */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/sasai-logo.png"
        alt="Sasai"
        className="select-none"
        style={{ height: 48, width: "auto", filter: "brightness(0) invert(1)" }}
      />
      <div className="w-full max-w-md rounded-2xl border bg-card p-8 shadow-xl">
        <div className="mb-6 flex justify-center">
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
