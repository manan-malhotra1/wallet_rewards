/**
 * Auth-flow API calls — anonymous endpoints + logout.
 *
 * Mirrors backend/app/modules/identity/router.py (Phase F.2). PINs and
 * OTPs are passed straight through to the backend — never persisted client
 * side, never logged.
 */
import { api, newIdempotencyKey } from '@/lib/api/client';

export interface AuthStartResponse {
  status: 'needs_otp' | 'needs_pin';
}

export interface OtpSendResponse {
  delivered: boolean;
  /** Populated only in local dev (OTP_DEV_RETURN=true). Display as a hint. */
  otp: string | null;
}

export interface OtpVerifyResponse {
  registration_token: string;
  expires_in: number;
}

export interface SessionTokenResponse {
  session_token: string;
  expires_in: number;
}

/** Probe whether (tenant, phone) is a returning user — drives screen branch. */
export async function authStart(
  tenantId: string,
  phone: string,
): Promise<AuthStartResponse> {
  return api<AuthStartResponse>({
    path: '/api/v1/identity/auth/start',
    method: 'POST',
    body: { tenant_id: tenantId, phone },
  });
}

/**
 * Send a fresh OTP. In dev the response includes the code for demoing.
 *
 * Args:
 *   tenantId: Resolved tenant for the request.
 *   phone: E.164 phone to deliver the OTP to.
 *   referralCode: Optional signup referral code. Sent only when a non-empty
 *     value is supplied; for a brand-new phone the backend captures it (reward
 *     paid at PIN-set). An invalid code fails with 422 `invalid_referral_code`.
 *
 * Raises:
 *   ApiError: 422 `invalid_referral_code` when the referral code isn't valid.
 */
export async function otpSend(
  tenantId: string,
  phone: string,
  referralCode?: string,
): Promise<OtpSendResponse> {
  const trimmed = referralCode?.trim();
  return api<OtpSendResponse>({
    path: '/api/v1/identity/otp/send',
    method: 'POST',
    body: {
      tenant_id: tenantId,
      phone,
      // Only include the field when the user actually entered a code, so the
      // login flow (and empty-code signups) keep the original narrow contract.
      ...(trimmed ? { referral_code: trimmed } : {}),
    },
  });
}

/** Verify the OTP; on success returns a short-lived registration_token. */
export async function otpVerify(
  tenantId: string,
  phone: string,
  otp: string,
): Promise<OtpVerifyResponse> {
  return api<OtpVerifyResponse>({
    path: '/api/v1/identity/otp/verify',
    method: 'POST',
    body: { tenant_id: tenantId, phone, otp },
  });
}

/**
 * Set the PIN using the registration_token from otpVerify.
 *
 * NOTE: this endpoint is declared `status_code=204` server-side, so we
 * follow up with an explicit /auth/pin call in the route to obtain the
 * session token. (Keeps the contract narrow — pin/set is single-purpose.)
 */
export async function pinSet(
  registrationToken: string,
  pin: string,
): Promise<void> {
  await api<void>({
    path: '/api/v1/identity/pin/set',
    method: 'POST',
    body: { registration_token: registrationToken, pin },
    idempotencyKey: newIdempotencyKey(),
  });
}

/** Authenticate with phone + PIN; issue a session_token. */
export async function authPin(
  tenantId: string,
  phone: string,
  pin: string,
): Promise<SessionTokenResponse> {
  return api<SessionTokenResponse>({
    path: '/api/v1/identity/auth/pin',
    method: 'POST',
    body: { tenant_id: tenantId, phone, pin },
  });
}

/** Invalidate the current bearer. Idempotent — safe to call without a token. */
export async function logout(): Promise<void> {
  try {
    await api<void>({
      path: '/api/v1/identity/auth/logout',
      method: 'POST',
      withAuth: true,
    });
  } catch {
    // Best-effort. We always clear local storage even if the server call fails.
  }
}
