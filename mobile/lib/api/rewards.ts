/**
 * Rewards API — authenticated read of the current user's reward catalog and
 * the "mark seen" write that dismisses a celebration.
 *
 * The mobile Rewards screen reads from /me/rewards: an `enabled` flag (rewards
 * may be off for an account), a `catalog` of rules the user can progress toward
 * (locked / in_progress / earned), and a `recent` list of rewards already
 * earned. Tenant + user are implicit in the session token — never passed in the
 * body (mirrors getMyLimits / getMyWallet).
 */
import { api } from '@/lib/api/client';

/**
 * Progress toward a catalog rule — how far the user is through the requirement.
 *
 * `current` / `target` drive the progress bar; `label` is a ready-to-render
 * caption (e.g. "2 / 3 P2P transfers") supplied by the backend.
 */
export interface RewardProgress {
  /** Steps completed toward the target. */
  current: number;
  /** Steps required to earn the reward. */
  target: number;
  /** Human caption for the progress (e.g. "2 / 3 P2P transfers"). */
  label: string;
}

/**
 * One reward rule the user can earn, with its current standing.
 *
 * `reward_value` is a Decimal string; for points rewards the currency is null
 * and the value is a whole-point count, for cashback the currency carries the
 * ISO code. `status` drives the pill/icon (earned = teal check, in_progress =
 * neutral, locked = muted).
 */
export interface RewardCatalogItem {
  /** The rule this catalog entry is for. */
  rule_id: string;
  /** Display name of the reward rule. */
  name: string;
  /** Longer description, or null when the rule has none. */
  description: string | null;
  /** Reward kind, e.g. "points" or "cashback". */
  reward_type: string;
  /** Reward magnitude as a Decimal string (points count or cashback value). */
  reward_value: string;
  /** ISO currency for cashback rewards, null for points. */
  currency: string | null;
  /** Where the user stands on this rule. */
  status: 'locked' | 'in_progress' | 'earned';
  /** Progress toward earning the reward. */
  progress: RewardProgress;
}

/**
 * A reward the user has already earned — the "Recent" feed and the source of
 * the home celebration (an unseen entry triggers the burst).
 */
export interface RecentReward {
  /** Unique id of this reward-issuance event (used to mark it seen). */
  reward_event_id: string;
  /** Name of the rule that granted it, or null if unavailable. */
  rule_name: string | null;
  /** Reward kind, e.g. "points" or "cashback". */
  reward_type: string;
  /** Reward magnitude as a Decimal string. */
  value: string;
  /** ISO currency for cashback, null for points. */
  currency: string | null;
  /** ISO-8601 timestamp the reward was earned. */
  earned_at: string;
  /** Whether the user has already seen (been celebrated for) this reward. */
  seen: boolean;
}

/** The full /me/rewards payload — the flag, the catalog, and recent earnings. */
export interface RewardsResponse {
  /** Whether rewards are available on this account at all. */
  enabled: boolean;
  /** Rules the user can progress toward / has earned. */
  catalog: RewardCatalogItem[];
  /** Rewards already earned, newest first. */
  recent: RecentReward[];
  /**
   * The signed-in user's own referral code to share, or null if they have none
   * (e.g. referrals disabled). Drives the "Refer a friend" card visibility.
   */
  referral_code: string | null;
}

/**
 * GET /me/rewards — the auth'd user's rewards state.
 *
 * Returns:
 *   The `enabled` flag plus the catalog and recent-reward feed. When rewards
 *   are disabled the caller should render the empty state and skip celebration.
 */
export async function getRewards(): Promise<RewardsResponse> {
  return api<RewardsResponse>({
    path: '/api/v1/identity/me/rewards',
    method: 'GET',
    withAuth: true,
  });
}

/**
 * POST /me/rewards/seen — mark reward-issuance events as seen so their home
 * celebration doesn't fire again.
 *
 * Args:
 *   ids: The `reward_event_id`s to acknowledge. A no-op when empty.
 *
 * Side effects:
 *   Persists the seen flag server-side; callers invalidate the rewards query
 *   afterward so the recent feed reflects it.
 */
export async function markRewardsSeen(ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  await api<{ marked: number }, { reward_event_ids: string[] }>({
    path: '/api/v1/identity/me/rewards/seen',
    method: 'POST',
    withAuth: true,
    body: { reward_event_ids: ids },
  });
}
