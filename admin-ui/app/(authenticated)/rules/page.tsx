/**
 * /rules → /campaigns redirect.
 *
 * The page was renamed in the Rule → Campaign rebrand. We keep a stub
 * here so deep links and bookmarked URLs still land. Next.js issues
 * the redirect server-side via `redirect()`, which throws a special
 * NEXT_REDIRECT error and produces a real 307.
 */
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default function LegacyRulesRedirect(): never {
  redirect("/campaigns");
}
