/**
 * User-type presentation helpers (Epic 13).
 *
 * `<UserTypeBadge>` renders the coloured pill on the user detail card, and
 * the exported constants drive the type selectors + parent-visibility logic
 * in the create-user and change-type dialogs. No client interactivity here,
 * so both server and client components can import it.
 */
import { Badge } from "@/components/ui/badge";
import type { UserType } from "@/lib/api-types";

/** Human labels for each type, in hierarchy order. */
export const USER_TYPE_OPTIONS: { value: UserType; label: string }[] = [
  { value: "consumer", label: "Consumer" },
  { value: "agent", label: "Agent" },
  { value: "super_agent", label: "Super agent" },
  { value: "merchant", label: "Merchant" },
  { value: "head_merchant", label: "Head merchant" },
];

/** Types that may hang under a parent (Decision D4). */
export const PARENT_REQUIRED_TYPES: UserType[] = ["agent", "merchant"];

/** Types that get a merchant_profiles row + collection account (Epic 17). */
export const MERCHANT_TYPES: UserType[] = ["merchant", "head_merchant"];

const TYPE_META: Record<UserType, { label: string; tone: "neutral" | "accent" | "warning" }> = {
  consumer: { label: "Consumer", tone: "neutral" },
  agent: { label: "Agent", tone: "accent" },
  super_agent: { label: "Super agent", tone: "accent" },
  merchant: { label: "Merchant", tone: "warning" },
  head_merchant: { label: "Head merchant", tone: "warning" },
};

export function UserTypeBadge({ type }: { type: UserType }) {
  const meta = TYPE_META[type] ?? { label: type, tone: "neutral" as const };
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}
