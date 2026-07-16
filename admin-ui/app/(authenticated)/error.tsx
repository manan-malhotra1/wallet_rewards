/**
 * Error boundary for the authenticated area — the fallback for any UNEXPECTED
 * throw during render/data-fetch. The common backend-unreachable case is
 * handled gracefully upstream in the layout (which renders the maintenance
 * panel without throwing, so the dev overlay never shows); this boundary
 * catches everything else and still renders the on-brand panel rather than
 * Next.js's raw runtime overlay.
 *
 * Error boundaries in the App Router must be client components.
 */
"use client";

import { ServiceUnavailable } from "@/components/branding/service-unavailable";
import { isBackendUnreachable } from "@/lib/is-backend-unreachable";

export default function AuthenticatedError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}): React.ReactElement {
  return (
    <ServiceUnavailable
      variant={isBackendUnreachable(error) ? "maintenance" : "error"}
      onRetry={reset}
      digest={error.digest}
    />
  );
}
