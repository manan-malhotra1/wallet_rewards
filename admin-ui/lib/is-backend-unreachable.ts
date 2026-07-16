/**
 * Pure, dependency-free classifier for "is the backend unreachable?" — safe to
 * import from both server components (the authenticated layout) and client
 * components (the error boundary). Inspects only the error *shape* (name,
 * message keywords, nested `cause.code`, and the `AggregateError` undici raises
 * when every resolved address fails); the raw text is never rendered.
 */

/** Network/connection markers that mean the API host couldn't be reached. */
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

/**
 * True when `error` looks like a backend-unreachable (network) failure rather
 * than an application/HTTP error. Classification only — no leakage to the UI.
 */
export function isBackendUnreachable(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const e = error as { name?: unknown; message?: unknown; cause?: { code?: unknown } };
  // undici's all-addresses-failed shape.
  if (e.name === "AggregateError") return true;
  const causeCode =
    e.cause && typeof e.cause.code === "string" ? e.cause.code : "";
  const haystack =
    `${String(e.name ?? "")} ${String(e.message ?? "")} ${causeCode}`.toLowerCase();
  return NETWORK_MARKERS.some((marker) => haystack.includes(marker));
}
