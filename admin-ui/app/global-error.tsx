/**
 * Root-level (last-resort) error boundary.
 *
 * Catches errors thrown in the root layout itself — the one place the
 * `(authenticated)/error.tsx` boundary cannot cover. Because it *replaces*
 * the root layout, it must render its own <html>/<body>, and the app's
 * global stylesheet may not be applied. All styling is therefore inline or
 * in a scoped <style> tag, using the Sasai brand palette (navy #144989,
 * teal #48C2CF) directly so the page still looks on-brand with zero CSS
 * dependencies. Copy mirrors the maintenance message; no raw error text or
 * stack is ever rendered.
 *
 * Error boundaries in the App Router must be client components.
 */
"use client";

export default function GlobalError({
  error,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}): React.ReactElement {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "1.5rem",
          background: "#f8fafc",
          color: "#0f172a",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
        }}
      >
        {/* Dark-mode without app CSS: honour the OS preference via a scoped
            media query overriding the light defaults above. */}
        <style>{`
          @media (prefers-color-scheme: dark) {
            body { background: #0b1220 !important; color: #e2e8f0 !important; }
            .sasai-card { background: #111a2e !important; border-color: #1e293b !important; }
            .sasai-muted { color: #94a3b8 !important; }
          }
        `}</style>
        <div
          className="sasai-card"
          style={{
            width: "100%",
            maxWidth: "28rem",
            textAlign: "center",
            border: "1px solid #e2e8f0",
            borderRadius: "1rem",
            background: "#ffffff",
            padding: "2rem",
            boxShadow: "0 10px 25px rgba(15, 23, 42, 0.08)",
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/sasai-logo.png"
            alt="Sasai"
            style={{ height: 32, width: "auto", margin: "0 auto 1.5rem" }}
          />
          <h1
            style={{
              margin: "0 0 0.5rem",
              fontSize: "1.125rem",
              fontWeight: 600,
              color: "#144989",
            }}
          >
            We&apos;ll be right back
          </h1>
          <p
            className="sasai-muted"
            style={{
              margin: "0 0 1.5rem",
              fontSize: "0.875rem",
              lineHeight: 1.5,
              color: "#475569",
            }}
          >
            We&apos;re currently upgrading your experience and will be back
            soon. Please contact your administrator for more information.
          </p>
          <a
            href="/login"
            style={{
              display: "inline-block",
              width: "100%",
              boxSizing: "border-box",
              padding: "0.5rem 1rem",
              borderRadius: "0.375rem",
              background: "#144989",
              color: "#ffffff",
              fontSize: "0.875rem",
              fontWeight: 500,
              textDecoration: "none",
            }}
          >
            Back to login
          </a>
          {error.digest && (
            <p
              className="sasai-muted"
              style={{
                margin: "1.5rem 0 0",
                fontFamily: "ui-monospace, SFMono-Regular, monospace",
                fontSize: "0.625rem",
                letterSpacing: "0.05em",
                color: "#94a3b8",
              }}
            >
              Reference: {error.digest}
            </p>
          )}
        </div>
      </body>
    </html>
  );
}
