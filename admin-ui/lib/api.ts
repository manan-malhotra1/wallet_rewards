/**
 * Backend API client — server-side only.
 *
 * Every call:
 *   1. Resolves the operator's Keycloak access token from the next-auth
 *      session.
 *   2. Forwards it as `Authorization: Bearer ...` to the FastAPI backend.
 *   3. Parses the JSON response or throws an `ApiError` carrying the
 *      backend's `{error_code, message}` shape.
 *
 * Never call this from a client component — `BACKEND_URL` is intentionally
 * not exposed to the browser. Wrap any client-driven mutation in a server
 * action that fronts these helpers.
 */
import "server-only";

import { auth } from "@/auth";

/**
 * Typed error thrown when the backend returns a non-2xx response. The
 * `error_code` mirrors `app/shared/exceptions` on the FastAPI side, so UI
 * code can switch on stable strings rather than HTTP status numbers alone.
 */
export class ApiError extends Error {
  status: number;
  errorCode: string;
  constructor(status: number, errorCode: string, message: string) {
    super(message);
    this.status = status;
    this.errorCode = errorCode;
    this.name = "ApiError";
  }
}

interface FetchOptions extends Omit<RequestInit, "body"> {
  /** Query string parameters. Undefined values are skipped. */
  query?: Record<string, string | number | undefined>;
  /** JSON body — will be stringified. */
  body?: unknown;
  /** When true, omit the Authorization header (rare — e.g. health checks). */
  skipAuth?: boolean;
  /** Idempotency-Key header — required for state-mutating endpoints. */
  idempotencyKey?: string;
}

function baseUrl(): string {
  const url = process.env.BACKEND_URL;
  if (!url) {
    throw new Error("BACKEND_URL is not configured");
  }
  return url.replace(/\/$/, "");
}

function buildUrl(path: string, query?: FetchOptions["query"]): string {
  const url = new URL(baseUrl() + path);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined) continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/**
 * Core fetch helper. Use the typed wrappers below (`apiGet`, `apiPost`,
 * etc) rather than calling this directly.
 */
async function apiFetch<T>(path: string, opts: FetchOptions = {}): Promise<T> {
  const { query, body, skipAuth, idempotencyKey, headers, ...rest } = opts;
  const finalHeaders: Record<string, string> = {
    Accept: "application/json",
    ...(headers as Record<string, string> | undefined),
  };
  if (body !== undefined) {
    finalHeaders["Content-Type"] = "application/json";
  }
  if (idempotencyKey) {
    finalHeaders["Idempotency-Key"] = idempotencyKey;
  }
  if (!skipAuth) {
    const session = await auth();
    if (!session?.accessToken) {
      throw new ApiError(401, "no_session", "Not authenticated");
    }
    finalHeaders["Authorization"] = `Bearer ${session.accessToken}`;
  }
  const res = await fetch(buildUrl(path, query), {
    ...rest,
    headers: finalHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (res.status === 204) {
    return undefined as T;
  }
  const text = await res.text();
  let payload: unknown = undefined;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      // Some 5xx pages return HTML — surface a generic message.
      payload = { error_code: "upstream_error", message: text.slice(0, 200) };
    }
  }
  if (!res.ok) {
    const errorCode =
      (payload as { error_code?: string } | undefined)?.error_code ??
      "upstream_error";
    const message =
      (payload as { message?: string } | undefined)?.message ??
      `Backend returned ${res.status}`;
    throw new ApiError(res.status, errorCode, message);
  }
  return payload as T;
}

export const apiGet = <T>(path: string, opts?: FetchOptions) =>
  apiFetch<T>(path, { ...opts, method: "GET" });

export const apiPost = <T>(path: string, body?: unknown, opts?: FetchOptions) =>
  apiFetch<T>(path, { ...opts, method: "POST", body });

export const apiPut = <T>(path: string, body?: unknown, opts?: FetchOptions) =>
  apiFetch<T>(path, { ...opts, method: "PUT", body });

export const apiPatch = <T>(path: string, body?: unknown, opts?: FetchOptions) =>
  apiFetch<T>(path, { ...opts, method: "PATCH", body });

export const apiDelete = <T>(path: string, opts?: FetchOptions) =>
  apiFetch<T>(path, { ...opts, method: "DELETE" });
