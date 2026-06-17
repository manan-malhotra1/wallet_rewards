/**
 * Server actions backing the login form.
 *
 * Lives next to `app/login/page.tsx`. The single action `loginAction`
 * delegates to next-auth's `signIn("credentials", …)`, which runs the
 * Credentials provider's `authorize()` callback in `auth.ts` (Keycloak
 * password grant). On success next-auth sets the session cookie and
 * raises Next.js's redirect signal to `redirectTo`; on failure it throws
 * an `AuthError` which we map to a form-state error message.
 */
"use server";

import { AuthError } from "next-auth";

import { signIn } from "@/auth";

export type LoginActionState = { error: string | null };

/**
 * Sanitise the post-login redirect target. We only honour same-origin,
 * path-only values so the login form cannot be weaponised into an open
 * redirect via `?from=https://evil.example`.
 */
function safeRedirect(value: FormDataEntryValue | null): string {
  const raw = typeof value === "string" ? value : "";
  if (raw.startsWith("/") && !raw.startsWith("//")) {
    return raw;
  }
  return "/dashboard";
}

/**
 * Form action invoked by `useActionState` on the login form. Returns an
 * error message on bad credentials; on success Next.js throws a redirect
 * before we get back to the return statement.
 */
export async function loginAction(
  _prev: LoginActionState,
  formData: FormData,
): Promise<LoginActionState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const from = safeRedirect(formData.get("from"));

  if (!email || !password) {
    return { error: "Email and password are required." };
  }

  try {
    await signIn("credentials", {
      email,
      password,
      redirectTo: from,
    });
  } catch (error) {
    // Next.js's internal redirect signal also propagates as a thrown
    // error — we must rethrow it so the framework can perform the
    // redirect. Anything that isn't an `AuthError` is rethrown.
    if (error instanceof AuthError) {
      return {
        error:
          error.type === "CredentialsSignin"
            ? "Invalid email or password."
            : "Unable to sign in. Please try again.",
      };
    }
    throw error;
  }
  // Unreachable when `signIn` redirects, but keeps the type system happy.
  return { error: null };
}
