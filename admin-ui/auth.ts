/**
 * next-auth v5 configuration.
 *
 * Single auth.ts at the project root — exports `handlers`, `auth`,
 * `signIn`, and `signOut`. Wires next-auth to the Keycloak realm
 * `wallet-platform` provisioned by `scripts/bootstrap_keycloak.py`.
 *
 * Login UX: we use the Credentials provider so the form lives in the admin
 * UI itself (no redirect to Keycloak's hosted login screen). The
 * `authorize()` callback exchanges username + password for tokens via
 * Keycloak's Direct Access Grants (password) endpoint, then surfaces the
 * access token, refresh token, and realm roles onto the next-auth session.
 *
 * Trade-off: direct-grant bypasses Keycloak's MFA / consent screens. We
 * accept this for an admin app gated behind the operator VPN; the backend
 * still independently validates every JWT it sees.
 */
import NextAuth, { type DefaultSession } from "next-auth";
import Credentials from "next-auth/providers/credentials";

declare module "next-auth" {
  /**
   * Augment the default Session shape so server components can read both
   * the operator's display info and their Keycloak access_token + realm
   * roles. Roles are pulled out of the JWT's `realm_access.roles` claim.
   */
  interface Session {
    accessToken?: string;
    error?: "refresh_failed";
    user: {
      id: string;
      username?: string;
      email?: string;
      roles: string[];
    } & DefaultSession["user"];
  }

  /**
   * Augment the User object returned by the Credentials `authorize()`
   * callback. These fields are read on initial sign-in inside the `jwt`
   * callback and persisted onto the JWT.
   */
  interface User {
    username?: string;
    roles?: string[];
    accessToken?: string;
    refreshToken?: string;
    accessTokenExpiresAt?: number;
  }

  /**
   * Augment the JWT we persist between requests with refresh-token state.
   * In next-auth v5 the JWT shape is exposed via the top-level `next-auth`
   * module declaration (no separate `next-auth/jwt` augmentation needed).
   */
  interface JWT {
    accessToken?: string;
    refreshToken?: string;
    accessTokenExpiresAt?: number;
    username?: string;
    roles?: string[];
    error?: "refresh_failed";
  }
}

/**
 * Build a Keycloak token-endpoint URL for the configured realm. Used for
 * both the initial password grant (sign-in) and the refresh-token grant.
 */
function tokenUrl(): string {
  const base = process.env.KEYCLOAK_URL ?? "http://localhost:8080";
  const realm = process.env.KEYCLOAK_REALM ?? "wallet-platform";
  return `${base}/realms/${realm}/protocol/openid-connect/token`;
}

/**
 * Decode the payload of a JWT without verifying its signature.
 *
 * Safe here because the token was just returned by Keycloak in the same
 * request — we trust it for session metadata extraction only. The backend
 * re-validates every JWT against Keycloak's JWKS on every API call.
 *
 * Edge-runtime compatible: uses `atob` + `TextDecoder` instead of `Buffer`,
 * so this module can be imported by `middleware.ts` without an Edge-
 * incompatibility build error.
 */
function decodeJwtPayload(jwt: string): Record<string, unknown> {
  const segment = jwt.split(".")[1] ?? "";
  const base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

/**
 * Refresh an expired access token against Keycloak. Returns the updated
 * JWT shape; on failure marks the token with an `error` so server
 * components can prompt re-auth.
 */
async function refreshAccessToken(token: {
  refreshToken?: string;
  [k: string]: unknown;
}): Promise<typeof token> {
  if (!token.refreshToken) {
    return { ...token, error: "refresh_failed" as const };
  }
  try {
    const params = new URLSearchParams({
      grant_type: "refresh_token",
      client_id: process.env.KEYCLOAK_CLIENT_ID ?? "admin-ui",
      client_secret: process.env.KEYCLOAK_CLIENT_SECRET ?? "",
      refresh_token: token.refreshToken,
    });
    const res = await fetch(tokenUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: params,
      cache: "no-store",
    });
    if (!res.ok) {
      return { ...token, error: "refresh_failed" as const };
    }
    const data = await res.json();
    return {
      ...token,
      accessToken: data.access_token,
      refreshToken: data.refresh_token ?? token.refreshToken,
      accessTokenExpiresAt: Math.floor(Date.now() / 1000) + data.expires_in,
      error: undefined,
    };
  } catch {
    return { ...token, error: "refresh_failed" as const };
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Credentials({
      // Field names here are informational only — the credentials are
      // submitted via our own form on `/login`. We pass the user-entered
      // value through to Keycloak's `username` parameter; Keycloak resolves
      // it against either the username or the email of the realm user
      // (`loginWithEmailAllowed` is on by default).
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      /**
       * Exchange the operator's email + password for Keycloak tokens via
       * the Direct Access Grants (password) endpoint. Returning `null`
       * causes next-auth to surface a `CredentialsSignin` error which the
       * login form renders as "invalid credentials".
       */
      async authorize(credentials) {
        const email = String(credentials?.email ?? "").trim();
        const password = String(credentials?.password ?? "");
        if (!email || !password) {
          return null;
        }
        const params = new URLSearchParams({
          grant_type: "password",
          client_id: process.env.KEYCLOAK_CLIENT_ID ?? "admin-ui",
          client_secret: process.env.KEYCLOAK_CLIENT_SECRET ?? "",
          username: email,
          password,
          scope: "openid",
        });
        let res: Response;
        try {
          res = await fetch(tokenUrl(), {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: params,
            cache: "no-store",
          });
        } catch {
          // Keycloak unreachable — treat as a sign-in failure rather than
          // crashing the auth route. The form will show a generic error.
          return null;
        }
        if (!res.ok) {
          // 401 invalid_grant (wrong creds), 400 (disabled user), etc.
          return null;
        }
        const data = (await res.json()) as {
          access_token: string;
          refresh_token: string;
          expires_in: number;
        };
        const claims = decodeJwtPayload(data.access_token) as {
          sub?: string;
          preferred_username?: string;
          email?: string;
          name?: string;
          realm_access?: { roles?: string[] };
        };
        return {
          id: claims.sub ?? "",
          email: claims.email,
          name: claims.name,
          username: claims.preferred_username,
          roles: claims.realm_access?.roles ?? [],
          accessToken: data.access_token,
          refreshToken: data.refresh_token,
          accessTokenExpiresAt:
            Math.floor(Date.now() / 1000) + data.expires_in,
        };
      },
    }),
  ],
  pages: {
    // Route unauthenticated browsers to our in-app login form (no Keycloak
    // hosted page redirect).
    signIn: "/login",
  },
  session: { strategy: "jwt" },
  callbacks: {
    /**
     * Persist the Keycloak access token + realm roles onto the next-auth
     * JWT. On initial sign-in next-auth passes the `User` object returned
     * by `authorize()`; on subsequent calls only `token` is set, and we
     * refresh against Keycloak when the access token is near expiry.
     */
    async jwt({ token, user }) {
      if (user) {
        const u = user as {
          id: string;
          email?: string;
          username?: string;
          roles?: string[];
          accessToken?: string;
          refreshToken?: string;
          accessTokenExpiresAt?: number;
        };
        token.accessToken = u.accessToken;
        token.refreshToken = u.refreshToken;
        token.accessTokenExpiresAt = u.accessTokenExpiresAt;
        token.roles = u.roles ?? [];
        token.username = u.username;
        token.email = u.email ?? token.email;
        token.sub = u.id;
        return token;
      }
      // Token already exists: refresh if it's about to expire (30s safety
      // window). Otherwise reuse as-is.
      const exp = token.accessTokenExpiresAt;
      if (typeof exp === "number" && exp - 30 < Math.floor(Date.now() / 1000)) {
        return refreshAccessToken(token);
      }
      return token;
    },
    /**
     * Expose the relevant JWT fields on the session object that React
     * components see via `useSession()` / the `auth()` helper.
     */
    async session({ session, token }) {
      const t = token as {
        accessToken?: string;
        error?: "refresh_failed";
        sub?: string;
        username?: string;
        email?: string;
        roles?: string[];
      };
      session.accessToken = t.accessToken;
      session.error = t.error;
      session.user = {
        ...session.user,
        id: t.sub ?? session.user?.id ?? "",
        username: t.username,
        email: t.email ?? session.user?.email ?? undefined,
        roles: t.roles ?? [],
      };
      return session;
    },
  },
});
