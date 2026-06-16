/**
 * Next-auth callback / signin routes.
 *
 * next-auth v5 exposes its route handlers as `{GET, POST}` on the
 * `handlers` object returned by `NextAuth(...)`. We re-export those here
 * so `/api/auth/*` resolves to the right method handler.
 */
import { handlers } from "@/auth";

export const { GET, POST } = handlers;
export const dynamic = "force-dynamic";
