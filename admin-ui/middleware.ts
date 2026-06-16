/**
 * Edge middleware — auth gate.
 *
 * Every authenticated route is wrapped in the `(authenticated)` group
 * which routes through this middleware. Unauthenticated browsers get
 * redirected to `/login`. The login page itself + the next-auth callback
 * are explicitly allowed through.
 */
import { NextResponse } from "next/server";

import { auth } from "@/auth";

const PUBLIC_PATHS = ["/login", "/api/auth"];

export default auth((req) => {
  const { pathname } = req.nextUrl;
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }
  if (!req.auth) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("from", pathname);
    return NextResponse.redirect(url);
  }
  // If the access token failed to refresh, re-auth the user — don't let
  // them keep clicking and seeing stale "401 invalid_token" responses.
  if (req.auth?.error === "refresh_failed") {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("from", pathname);
    url.searchParams.set("reason", "refresh_failed");
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
});

export const config = {
  // Run the auth check on every page except Next's internals + static
  // assets. Public Next.js assets must NOT be auth-gated or rendering
  // freezes on the loading flash.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|svg|gif|webp|ico)$).*)",
  ],
};
