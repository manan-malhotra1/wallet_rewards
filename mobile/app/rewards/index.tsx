/**
 * /rewards — the current user's rewards: progress toward reward rules and the
 * rewards they've already earned (Sasai Rewards).
 *
 * Navy gradient header + a clay body. When rewards are disabled for the account
 * we show a simple empty state. Otherwise a "Progress" section renders each
 * catalog rule as a clay card — its name, the reward it grants, a progress bar
 * (current / target) with a caption, and a status pill (earned / in progress /
 * locked). A "Recent" section lists earned rewards in the ActivityRow style.
 *
 * Data comes from GET /me/rewards (see lib/api/rewards.ts). Points are whole
 * counts; cashback is money formatted in its own currency — never assume ZAR.
 */
import { Pressable, Share, ScrollView } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { ActivityRow } from '@/components/ui/ActivityRow';
import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { ClayInset, ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import {
  getRewards,
  type RecentReward,
  type RewardCatalogItem,
} from '@/lib/api/rewards';
import { qk } from '@/lib/query';
import { formatMoney } from '@/lib/format';

/**
 * Human-readable reward amount: points render as "{value} points", cashback as
 * money in its own currency (e.g. "R 25.00"). Shared by the catalog card and
 * the recent-reward row so the two feeds phrase a reward identically.
 *
 * Args:
 *   rewardType: The reward kind ("points" | "cashback" | …).
 *   value: The reward magnitude as a Decimal string.
 *   currency: ISO currency for cashback, null/undefined for points.
 */
function rewardText(rewardType: string, value: string, currency: string | null): string {
  if (rewardType === 'cashback' && currency) {
    return formatMoney(value, currency);
  }
  // Points (and any non-cashback kind) render as a whole-number point count.
  const points = parseFloat(value);
  const count = Number.isFinite(points) ? Math.round(points) : 0;
  return `${count.toLocaleString('en-ZA')} points`;
}

/** Per-status pill styling: label, tint background, and text/icon colour. */
function statusPill(status: RewardCatalogItem['status'], colors: ReturnType<typeof useColors>) {
  switch (status) {
    case 'earned':
      return { label: 'Earned', bg: colors.chipTealBg, fg: colors.teal, icon: 'checkmark-circle' as const };
    case 'in_progress':
      return { label: 'In progress', bg: colors.clayInset, fg: colors.textMuted, icon: 'time' as const };
    default:
      return { label: 'Locked', bg: colors.clayInset, fg: colors.textFaint, icon: 'lock-closed' as const };
  }
}

/**
 * Fraction of a rule's progress that's complete, clamped to [0, 1].
 *
 * Guards a zero/invalid target so the bar never divides by zero or overflows.
 */
function progressFraction(current: number, target: number): number {
  if (!Number.isFinite(target) || target <= 0) return 0;
  const frac = current / target;
  if (!Number.isFinite(frac)) return 0;
  return Math.max(0, Math.min(1, frac));
}

/** Thin clay-inset progress track with a teal fill at `fraction` (0–1). */
function ProgressBar({ fraction }: { fraction: number }) {
  const colors = useColors();
  return (
    <View
      height={7}
      borderRadius={4}
      backgroundColor={colors.clayInset}
      overflow="hidden"
      marginTop={10}
    >
      <View
        height={7}
        borderRadius={4}
        backgroundColor={colors.teal}
        width={`${Math.round(fraction * 100)}%`}
      />
    </View>
  );
}

/** A single catalog rule as a clay card: name, reward, progress bar, status. */
function CatalogCard({ item }: { item: RewardCatalogItem }) {
  const colors = useColors();
  const pill = statusPill(item.status, colors);
  const fraction = progressFraction(item.progress.current, item.progress.target);

  return (
    <ClaySurface depth="soft" radius={18} paddingHorizontal={16} paddingVertical={16}>
      <XStack alignItems="flex-start" justifyContent="space-between" gap={12}>
        <YStack flex={1} gap={3}>
          <Text fontFamily="PlusJakartaSans-Bold" fontSize={14.5} color={colors.text}>
            {item.name}
          </Text>
          <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={13} color={colors.teal}>
            {rewardText(item.reward_type, item.reward_value, item.currency)}
          </Text>
          {item.description ? (
            <Text
              fontFamily="PlusJakartaSans-Medium"
              fontSize={11.5}
              color={colors.textMuted}
              marginTop={1}
            >
              {item.description}
            </Text>
          ) : null}
        </YStack>
        <XStack
          alignItems="center"
          gap={5}
          backgroundColor={pill.bg}
          paddingHorizontal={9}
          paddingVertical={5}
          borderRadius={20}
        >
          <Ionicons name={pill.icon} size={12} color={pill.fg} />
          <Text fontFamily="PlusJakartaSans-Bold" fontSize={10.5} color={pill.fg}>
            {pill.label}
          </Text>
        </XStack>
      </XStack>

      <ProgressBar fraction={fraction} />

      <Text
        fontFamily="PlusJakartaSans-Medium"
        fontSize={11.5}
        color={colors.textMuted}
        marginTop={7}
      >
        {item.progress.label}
      </Text>
    </ClaySurface>
  );
}

/** Format an ISO timestamp as "Today · HH:mm" or "DD MMM · HH:mm". */
function earnedSubtitle(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return '';
  const now = new Date();
  const sameDay =
    now.getFullYear() === when.getFullYear() &&
    now.getMonth() === when.getMonth() &&
    now.getDate() === when.getDate();
  const time = when.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  return sameDay
    ? `Today · ${time}`
    : `${when.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })} · ${time}`;
}

/** One earned reward, in the shared ActivityRow (gift icon) style. */
function RecentRow({ reward, noBorder }: { reward: RecentReward; noBorder: boolean }) {
  return (
    <ActivityRow
      category="reward"
      title={reward.rule_name ?? 'Reward earned'}
      subtitle={earnedSubtitle(reward.earned_at)}
      amount={`+${rewardText(reward.reward_type, reward.value, reward.currency)}`}
      positive
      noBorder={noBorder}
    />
  );
}

/**
 * "Refer a friend" card — surfaces the user's own referral code prominently
 * with a Share action (react-native's native sheet; no extra dep). Rendered
 * only when the user has a code; the caller hides it when `referral_code` is
 * null. Sharing lets them hand the code to a friend who earns both sides points
 * on sign-up.
 *
 * Args:
 *   code: The signed-in user's referral code (non-null by the time it renders).
 */
function ReferralCard({ code }: { code: string }) {
  const colors = useColors();

  /** Open the OS share sheet pre-filled with the code and an invite line. */
  async function onShare() {
    await Share.share({
      message: `Join me on Sasai! Use my referral code ${code} when you sign up and we both earn points.`,
    });
  }

  return (
    <ClaySurface depth="soft" radius={20} paddingHorizontal={16} paddingVertical={16}>
      <XStack alignItems="center" gap={10}>
        <View
          width={40}
          height={40}
          borderRadius={20}
          backgroundColor={colors.chipTealBg}
          alignItems="center"
          justifyContent="center"
        >
          <Ionicons name="gift" size={20} color={colors.teal} />
        </View>
        <YStack flex={1} gap={2}>
          <Text fontFamily="PlusJakartaSans-Bold" fontSize={15} color={colors.text}>
            Refer a friend
          </Text>
          <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color={colors.textMuted}>
            Share this code — you both earn points when they sign up.
          </Text>
        </YStack>
      </XStack>

      <XStack alignItems="center" gap={10} marginTop={14}>
        <ClayInset radius={14} flex={1} paddingVertical={12} alignItems="center">
          <Text
            fontFamily="PlusJakartaSans-ExtraBold"
            fontSize={20}
            color={colors.navy}
            letterSpacing={3}
          >
            {code}
          </Text>
        </ClayInset>
        <Pressable
          onPress={onShare}
          accessibilityRole="button"
          accessibilityLabel="Share referral code"
        >
          <XStack
            alignItems="center"
            gap={6}
            backgroundColor={colors.navy}
            paddingHorizontal={16}
            height={48}
            borderRadius={14}
          >
            <Ionicons name="share-social" size={16} color={colors.textOnDark} />
            <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color={colors.textOnDark}>
              Share
            </Text>
          </XStack>
        </Pressable>
      </XStack>
    </ClaySurface>
  );
}

/** Small uppercase section heading (e.g. "Progress", "Recent"). */
function SectionTitle({ children }: { children: string }) {
  const colors = useColors();
  return (
    <Text
      fontFamily="PlusJakartaSans-Bold"
      fontSize={12}
      color={colors.textMuted}
      textTransform="uppercase"
      letterSpacing={0.8}
      paddingHorizontal={4}
    >
      {children}
    </Text>
  );
}

/** Rewards screen. */
export default function RewardsScreen() {
  const colors = useColors();
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.rewards(),
    queryFn: getRewards,
  });

  const catalog = data?.catalog ?? [];
  const recent = data?.recent ?? [];

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <GradientHeader paddingBottom={24}>
          <HeaderBack title="Rewards" />
          <Text
            fontFamily="PlusJakartaSans-Medium"
            fontSize={12.5}
            color="rgba(255,255,255,0.85)"
            marginTop={10}
          >
            Earn points and cashback as you use Sasai.
          </Text>
        </GradientHeader>

        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingHorizontal: 18, paddingTop: 18, paddingBottom: 40 }}
          showsVerticalScrollIndicator={false}
        >
          {isLoading ? (
            <YStack alignItems="center" paddingVertical={40}>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color={colors.textMuted}>
                Loading your rewards…
              </Text>
            </YStack>
          ) : isError ? (
            <YStack alignItems="center" paddingVertical={40}>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color={colors.danger}>
                Couldn't load your rewards. Pull back and try again.
              </Text>
            </YStack>
          ) : !data?.enabled ? (
            <YStack alignItems="center" gap={12} paddingVertical={44}>
              <View
                width={64}
                height={64}
                borderRadius={32}
                backgroundColor={colors.clayInset}
                alignItems="center"
                justifyContent="center"
              >
                <Ionicons name="gift-outline" size={30} color={colors.textFaint} />
              </View>
              <Text fontFamily="PlusJakartaSans-Bold" fontSize={14.5} color={colors.text}>
                Rewards aren't available yet
              </Text>
              <Text
                fontFamily="PlusJakartaSans-Medium"
                fontSize={12.5}
                color={colors.textMuted}
                textAlign="center"
                maxWidth={260}
              >
                Rewards aren't enabled on this account. Check back soon.
              </Text>
            </YStack>
          ) : (
            <YStack gap={26}>
              {/* Refer a friend — only when the user has a code to share. */}
              {data?.referral_code ? <ReferralCard code={data.referral_code} /> : null}

              {/* Progress — the rules the user can earn. */}
              <YStack gap={10}>
                <SectionTitle>Progress</SectionTitle>
                {catalog.length === 0 ? (
                  <ClaySurface depth="soft" radius={18} paddingVertical={22} alignItems="center">
                    <Text
                      fontFamily="PlusJakartaSans-Medium"
                      fontSize={12.5}
                      color={colors.textMuted}
                    >
                      No rewards to work toward right now.
                    </Text>
                  </ClaySurface>
                ) : (
                  catalog.map((item) => <CatalogCard key={item.rule_id} item={item} />)
                )}
              </YStack>

              {/* Recent — rewards already earned. */}
              {recent.length > 0 ? (
                <YStack gap={10}>
                  <SectionTitle>Recent</SectionTitle>
                  <ClaySurface depth="soft" radius={20} paddingHorizontal={14}>
                    {recent.map((r, i) => (
                      <RecentRow
                        key={r.reward_event_id}
                        reward={r}
                        noBorder={i === recent.length - 1}
                      />
                    ))}
                  </ClaySurface>
                </YStack>
              ) : null}
            </YStack>
          )}
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}
