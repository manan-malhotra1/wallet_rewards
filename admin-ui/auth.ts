/**
 * next-auth v5 configuration.
 *
 * Single auth.ts at the project root — exports `handlers`, `auth`,
 * `signIn`, and `signOut`. Wires next-auth to the Keycloak realm
 * `wallet-platform` provisioned by `scripts/bootstrap_keycloak.py`.
 *
 * Important: we cache the Keycloak `access_token` on the session so server
 * components can forward it to the backend FastAPI service. Refresh-on-
 * expiry uses the standard refresh-token grant.
 */
import NextAuth, { type DefaultSession } from "next-auth";
import Keycloak from "next-auth/providers/keycloak";

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
 * Build a Keycloak token-endpoint URL for the configured realm. We don't
 * use the discovery doc because next-auth's Keycloak provider already
 * handles initial sign-in; we hit `token` directly for refresh.
 */
function tokenUrl(): string {
  const base = process.env.KEYCLOAK_URL ?? "http://localhost:8080";
  const realm = process.env.KEYCLOAK_REALM ?? "wallet-platform";
  return `${base}/realms/${realm}/protocol/openid-connect/token`;
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
    Keycloak({
      clientId: process.env.KEYCLOAK_CLIENT_ID ?? "admin-ui",
      clientSecret: process.env.KEYCLOAK_CLIENT_SECRET ?? "",
      issuer: `${process.env.KEYCLOAK_URL ?? "http://localhost:8080"}/realms/${process.env.KEYCLOAK_REALM ?? "wallet-platform"}`,
    }),
  ],
  pages: {
    // Route unauthenticated browsers to our own login page (which renders a
    // single "Sign in with Keycloak" button) rather than next-auth's
    // default form. Cleaner branding + a single integration test target.
    signIn: "/login",
  },
  session: { strategy: "jwt" },
  callbacks: {
    /**
     * Persist the Keycloak access token + realm roles onto the next-auth
     * JWT. Runs on initial sign-in and every subsequent JWT validation.
     */
    async jwt({ token, account, profile }) {
      if (account && profile) {
        token.accessToken = account.access_token;
        token.refreshToken = account.refresh_token;
        token.accessTokenExpiresAt = account.expires_at;
        // Keycloak puts realm roles in `realm_access.roles`. We surface
        // them to the session so the UI can hide/show admin-only actions.
        const realmAccess = (profile as { realm_access?: { roles?: string[] } })
          .realm_access;
        token.roles = realmAccess?.roles ?? [];
        token.username =
          (profile as { preferred_username?: string }).preferred_username ??
          profile.name ?? undefined;
        token.email = (profile.email as string | undefined) ?? token.email;
        token.sub = profile.sub as string | undefined;
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
