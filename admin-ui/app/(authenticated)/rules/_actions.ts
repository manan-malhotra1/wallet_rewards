"use server";

/**
 * Legacy alias module — the page rename moved everything to
 * `/campaigns`. Anything still importing from
 * `@/app/(authenticated)/rules/_actions` is routed here. New code
 * MUST import from `@/app/(authenticated)/campaigns/_actions` instead.
 */
export {
  createCampaignWithBudgetAction,
  createRuleWithBudgetAction,
} from "@/app/(authenticated)/campaigns/_actions";

export type {
  CreateCampaignResult,
  CreateRuleResult,
  InlineBudgetInput,
} from "@/app/(authenticated)/campaigns/_actions";
