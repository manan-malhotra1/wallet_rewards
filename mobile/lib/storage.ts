/**
 * Secure storage wrapper over expo-secure-store.
 *
 * Stores three keys used across the auth flow:
 *   - session_token       : opaque bearer issued by /auth/pin or /pin/set
 *   - last_phone          : E.164 phone the user last logged in with
 *   - registration_token  : short-lived token between /otp/verify and /pin/set
 *
 * NEVER log the session_token or registration_token — per
 * .claude/rules/compliance-fintech.md, credentials and tokens must never
 * appear in logs.
 */
import * as SecureStore from 'expo-secure-store';

const KEY_SESSION_TOKEN = 'sasai.session_token';
const KEY_LAST_PHONE = 'sasai.last_phone';
const KEY_REGISTRATION_TOKEN = 'sasai.registration_token';

/** Read the cached session token. Returns null if absent. */
export async function getSessionToken(): Promise<string | null> {
  return SecureStore.getItemAsync(KEY_SESSION_TOKEN);
}

/** Persist the bearer token after a successful PIN auth or PIN set. */
export async function setSessionToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(KEY_SESSION_TOKEN, token);
}

/** Remove the cached session token (sign-out / 401 fallback). */
export async function clearSessionToken(): Promise<void> {
  await SecureStore.deleteItemAsync(KEY_SESSION_TOKEN);
}

/** Read the last phone used at login. Drives screen pre-fill. */
export async function getLastPhone(): Promise<string | null> {
  return SecureStore.getItemAsync(KEY_LAST_PHONE);
}

/** Remember the phone so subsequent OTP / PIN screens can recover it. */
export async function setLastPhone(phone: string): Promise<void> {
  await SecureStore.setItemAsync(KEY_LAST_PHONE, phone);
}

/** Clear the cached phone (used on full sign-out). */
export async function clearLastPhone(): Promise<void> {
  await SecureStore.deleteItemAsync(KEY_LAST_PHONE);
}

/** Read the short-lived registration token (between OTP and PIN set). */
export async function getRegistrationToken(): Promise<string | null> {
  return SecureStore.getItemAsync(KEY_REGISTRATION_TOKEN);
}

/** Persist the short-lived registration token. Consumed by /pin/set. */
export async function setRegistrationToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(KEY_REGISTRATION_TOKEN, token);
}

/** Clear the registration token (after /pin/set consumes it). */
export async function clearRegistrationToken(): Promise<void> {
  await SecureStore.deleteItemAsync(KEY_REGISTRATION_TOKEN);
}

/** Clear everything — used on sign-out so the next launch routes to /auth/phone. */
export async function clearAll(): Promise<void> {
  await Promise.all([
    clearSessionToken(),
    clearLastPhone(),
    clearRegistrationToken(),
  ]);
}
