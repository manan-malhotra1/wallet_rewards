/**
 * Typed fetch wrapper for every backend call.
 *
 * Responsibilities:
 *   - Build absolute URLs from env.backendUrl
 *   - Attach Bearer token when `withAuth: true`
 *   - Attach `Idempotency-Key` for state-mutating requests
 *   - Parse JSON success or { error_code, message } failure
 *   - Throw a typed ApiError subclass on non-2xx
 *
 * NEVER log the response body or the Authorization header — they may
 * contain session tokens. Mask before logging if you must.
 */
import { env } from '@/lib/env';
import { getSessionToken } from '@/lib/storage';
import { ApiError, toTypedError } from '@/lib/api/errors';

interface ApiRequest<TBody> {
  /** Path starting with `/api/v1/...`. */
  path: string;
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: TBody;
  /** Attach the cached session token as Bearer. Default false. */
  withAuth?: boolean;
  /** Provide a stable idempotency key for state-mutating calls. */
  idempotencyKey?: string;
}

/** UUID v4-ish. Good enough for client-generated idempotency keys. */
export function newIdempotencyKey(): string {
  // crypto.randomUUID is available in React Native 0.71+ via Hermes/JSC.
  // Fall back to a timestamp+random hybrid if unavailable.
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  const rand = Math.random().toString(36).slice(2, 10);
  return `cli-${Date.now()}-${rand}`;
}

async function buildHeaders(
  withAuth: boolean,
  idempotencyKey: string | undefined,
  hasBody: boolean,
): Promise<Record<string, string>> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };
  if (hasBody) headers['Content-Type'] = 'application/json';
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
  if (withAuth) {
    const token = await getSessionToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

async function parseError(res: Response): Promise<ApiError> {
  // Defaults if the body isn't JSON or doesn't follow the contract.
  let errorCode = `http_${res.status}`;
  let message = res.statusText || 'Request failed';
  try {
    const data = await res.json();
    if (typeof data?.error_code === 'string') errorCode = data.error_code;
    if (typeof data?.message === 'string') message = data.message;
    // FastAPI 422 returns `{ detail: [...] }`. Surface a short summary.
    if (res.status === 422 && Array.isArray(data?.detail)) {
      errorCode = 'validation_error';
      message = data.detail[0]?.msg ?? message;
    }
  } catch {
    // Non-JSON body — keep defaults.
  }
  return toTypedError(res.status, errorCode, message);
}

/**
 * Execute a backend call. Returns the parsed JSON on 2xx, throws on 4xx/5xx.
 * Status 204 returns `null` (no body).
 */
export async function api<TResp, TBody = unknown>(
  req: ApiRequest<TBody>,
): Promise<TResp> {
  const url = `${env.backendUrl}${req.path}`;
  const hasBody = req.body !== undefined;
  const headers = await buildHeaders(
    req.withAuth === true,
    req.idempotencyKey,
    hasBody,
  );

  const res = await fetch(url, {
    method: req.method,
    headers,
    body: hasBody ? JSON.stringify(req.body) : undefined,
  });

  if (!res.ok) throw await parseError(res);
  // 204 No Content
  if (res.status === 204) return null as unknown as TResp;
  // Some endpoints return JSON, some text — we always expect JSON in this app.
  return (await res.json()) as TResp;
}
