/**
 * X-Sasai-Signature builder. Mirrors `backend/app/auth/hmac.py`'s
 * `build_signature_header`: canonical string `{ts}.{body}`, HMAC-SHA256
 * with the source's shared_secret, header is `t={ts},v1={hex}`.
 *
 * Pure server-side: needs the secret, must never reach the browser.
 */
import "server-only";

import crypto from "node:crypto";

export function signEventBody(rawBody: string, secret: string): string {
  if (!secret) {
    throw new Error(
      "EVENT_SOURCE_SECRET is empty. Run `make seed` and copy the printed secret.",
    );
  }
  const ts = Math.floor(Date.now() / 1000);
  const digest = crypto
    .createHmac("sha256", secret)
    .update(`${ts}.${rawBody}`)
    .digest("hex");
  return `t=${ts},v1=${digest}`;
}

/**
 * Alias of {@link signEventBody} for the partner external-API paths
 * (/external/fund, /external/withdraw, /external/users). Identical scheme —
 * canonical `{ts}.{body}`, HMAC-SHA256 — but signed with the API key's secret
 * instead of an event source's. Kept as a named alias so call sites read
 * clearly and the empty-secret error message can be interpreted in context.
 */
export function signExternalBody(rawBody: string, secret: string): string {
  return signEventBody(rawBody, secret);
}
