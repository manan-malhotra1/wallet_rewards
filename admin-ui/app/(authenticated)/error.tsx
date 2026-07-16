/**
 * Error boundary for the authenticated area.
 *
 * Catches any error thrown while rendering or data-fetching in a server or
 * client component under `(authenticated)/` — most commonly the backend
 * being unreachable during SSR (`getActiveTenantId` → `apiFetch` in
 * `lib/api.ts` throws). Instead of Next.js's raw runtime overlay, it shows
 * a centred, on-brand "service unavailable / maintenance" page.
 *
 * Error boundaries in the App Router must be client components.
 */
"use client";

import Link from "next/link";

import { SasaiLogo } from "@/components/branding/sasai-logo";
import { Button } from "@/components/ui/button";

/**
 * Heuristically decide whether an error is a backend-unreachable (network)
 * failure rather than an application error.
 *
 * We only ever inspect the error *shape* (name, message keywords, nested
 * `cause.code`, and the AggregateError produced by `undici` when every DNS
 * result fails). The raw message is never rendered — see the component —
 * so this stays a classification-only read, no leakage to the UI.
 *
 * Returns true for connection-style failures (`fetch failed`,
 * `ECONNREFUSED`, `ENOTFOUND`, `UND_ERR_*`, etc).
 */
function isConnectionError(error: Error): boolean {
  // Walk the message plus any nested cause code into one lowercase haystack.
  const cause = (error as { cause?: { code?: unknown } }).cause;
  const causeCode =
    cause && typeof cause.code === "string" ? cause.code : "";
  const haystack = `${error.name} ${error.message} ${causeCode}`.toLowerCase();

  const NETWORK_MARKERS = [
    "fetch failed",
    "econnrefused",
    "enotfound",
    "eai_again",
    "econnreset",
    "etimedout",
    "und_err",
    "network",
    "socket hang up",
    "failed to fetch",
  ];

  // undici raises an AggregateError ("") when every resolved address fails
  // to connect — treat that as a connection problem too.
  if (error.name === "AggregateError") return true;

  return NETWORK_MARKERS.some((marker) => haystack.includes(marker));
}

/**
 * Branded fallback shown when the authenticated area throws.
 *
 * Two copy variants share one layout: a "maintenance" message for
 * backend-unreachable errors and a generic "something went wrong" message
 * for everything else. The raw error text and stack are never surfaced —
 * only the optional `digest` is shown (muted) as a support reference.
 */
export default function AuthenticatedError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}): React.ReactElement {
  const maintenance = isConnectionError(error);

  const headline = maintenance
    ? "We'll be right back"
    : "Something went wrong";
  const body = maintenance
    ? "We're currently upgrading your experience and will be back soon. Please contact your administrator for more information."
    : "An unexpected error stopped this page from loading. Try again, and if it keeps happening, contact your administrator.";

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-md rounded-2xl border bg-card p-8 text-center shadow-xl">
        <div className="mb-6 flex items-center justify-center gap-3">
          <SasaiLogo height={32} />
          <span className="rounded-full border bg-muted/50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Admin Console
          </span>
        </div>
        <h1 className="mb-2 text-lg font-semibold text-foreground">
          {headline}
        </h1>
        <p className="mb-6 text-sm text-muted-foreground">{body}</p>
        <div className="flex flex-col items-center gap-3">
          <Button onClick={reset} className="w-full">
            Try again
          </Button>
          <Button asChild variant="ghost" className="w-full">
            <Link href="/login">Back to login</Link>
          </Button>
        </div>
        {error.digest && (
          <p className="mt-6 font-mono text-[10px] tracking-wide text-muted-foreground/70">
            Reference: {error.digest}
          </p>
        )}
      </div>
    </div>
  );
}
