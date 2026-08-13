/**
 * Branded full-screen "service unavailable / maintenance" panel.
 *
 * Shown when the backend is unreachable (rendered directly by the
 * authenticated layout, so no error is thrown and the dev overlay never
 * appears) or as the error-boundary fallback for unexpected errors. Two copy
 * variants share one layout; the raw error is never surfaced — only an
 * optional `digest` as a support reference.
 */
"use client";

import Link from "next/link";

import { SasaiLogo } from "@/components/branding/sasai-logo";
import { Button } from "@/components/ui/button";

export function ServiceUnavailable({
  variant = "maintenance",
  onRetry,
  digest,
}: {
  /** "maintenance" = backend unreachable; "error" = unexpected app error. */
  variant?: "maintenance" | "error";
  /** Retry handler; defaults to a full reload when omitted. */
  onRetry?: () => void;
  /** Opaque support reference (Next.js error digest), shown muted if present. */
  digest?: string;
}): React.ReactElement {
  const maintenance = variant === "maintenance";
  const headline = maintenance ? "We'll be right back" : "Something went wrong";
  const body = maintenance
    ? "We're currently upgrading your experience and will be back soon. Please contact your administrator for more information."
    : "An unexpected error stopped this page from loading. Try again, and if it keeps happening, contact your administrator.";

  const retry =
    onRetry ??
    (() => {
      if (typeof window !== "undefined") window.location.reload();
    });

  return (
    <div
      className="flex min-h-screen items-center justify-center p-6"
      style={{ backgroundColor: "#144989" }}
    >
      <div className="glass-panel w-full max-w-md rounded-2xl p-8 text-center">
        <div className="mb-6 flex items-center justify-center gap-3">
          <SasaiLogo height={32} />
          <span className="rounded-full border bg-muted/50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Admin Console
          </span>
        </div>
        <h1 className="mb-2 text-lg font-semibold text-foreground">{headline}</h1>
        <p className="mb-6 text-sm text-muted-foreground">{body}</p>
        <div className="flex flex-col items-center gap-3">
          <Button onClick={retry} className="w-full">
            Try again
          </Button>
          <Button asChild variant="ghost" className="w-full">
            <Link href="/login">Back to login</Link>
          </Button>
        </div>
        {digest && (
          <p className="mt-6 font-mono text-[10px] tracking-wide text-muted-foreground/70">
            Reference: {digest}
          </p>
        )}
      </div>
    </div>
  );
}
