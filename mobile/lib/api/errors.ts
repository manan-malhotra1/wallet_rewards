/**
 * Typed errors used across the API layer.
 *
 * The backend returns errors as `{ error_code, message }`. We map a few
 * well-known codes to subclasses so call sites can branch with typed checks
 * (no string sniffing). Anything else falls through as a generic ApiError.
 *
 * NOTE: never include credentials in the message. Phone numbers shown to
 * users are masked at the UI layer, not here.
 */

/** Generic API failure — non-2xx response with parsed error_code/message. */
export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string;

  constructor(status: number, errorCode: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.errorCode = errorCode;
  }
}

/** 401 step_up_required — the action needs a step-up PIN sheet. */
export class StepUpRequired extends ApiError {
  constructor(message: string) {
    super(401, 'step_up_required', message);
    this.name = 'StepUpRequired';
  }
}

/** 401 invalid_step_up_pin — wrong PIN entered in a step-up flow. */
export class InvalidStepUpPin extends ApiError {
  constructor(message: string) {
    super(401, 'invalid_step_up_pin', message);
    this.name = 'InvalidStepUpPin';
  }
}

/** 401 session_expired — the bearer token is no longer valid. */
export class SessionExpired extends ApiError {
  constructor(message: string) {
    super(401, 'session_expired', message);
    this.name = 'SessionExpired';
  }
}

/** 401 invalid_pin — wrong PIN at the standalone login screen. */
export class InvalidPin extends ApiError {
  constructor(message: string) {
    super(401, 'invalid_pin', message);
    this.name = 'InvalidPin';
  }
}

/** 429 rate_limited / lockout — show "too many attempts" UI. */
export class RateLimited extends ApiError {
  constructor(errorCode: string, message: string) {
    super(429, errorCode, message);
    this.name = 'RateLimited';
  }
}

/**
 * Map a parsed `{error_code, message}` body + status to the right subclass.
 * Falls back to ApiError for anything not specifically handled.
 */
export function toTypedError(
  status: number,
  errorCode: string,
  message: string,
): ApiError {
  if (status === 401) {
    if (errorCode === 'step_up_required') return new StepUpRequired(message);
    if (errorCode === 'invalid_step_up_pin')
      return new InvalidStepUpPin(message);
    if (errorCode === 'session_expired') return new SessionExpired(message);
    if (errorCode === 'invalid_pin') return new InvalidPin(message);
  }
  if (status === 429) return new RateLimited(errorCode, message);
  return new ApiError(status, errorCode, message);
}
