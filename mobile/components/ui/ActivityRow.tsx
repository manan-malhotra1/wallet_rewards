/**
 * ActivityRow — one row in the home preview and the Transactions list.
 *
 * Layout: tinted icon tile (42×42, 13px radius) + two-line label
 * (title in ink, sub-line in muted gray) + amount on the right (positive
 * credits in success-green, debits in ink). An optional `subAmount` line
 * (e.g., "Wallet" / "EcoCash") sits below the amount.
 *
 * Tint colors per category are chosen to look soft against the white card.
 */
import { Text, XStack, YStack } from 'tamagui';

import { ClayIconTile } from '@/components/clay';

type Category = 'received' | 'sent' | 'bill' | 'airtime' | 'reward' | 'reward-redeem' | 'referral' | 'generic';

interface Props {
  /** Tile category — drives icon + tint. */
  category: Category;
  /** Primary line (e.g., "Maria Ncube"). */
  title: string;
  /** Secondary line (e.g., "Received · 10:24"). */
  subtitle: string;
  /** Display amount, already formatted (e.g., "+$120.00"). */
  amount: string;
  /** Optional small label under the amount (e.g., "Wallet", "Token"). */
  subAmount?: string;
  /** Credit (positive amount) → green text. Debit → ink. Defaults by category. */
  positive?: boolean;
  /** Hide the row's bottom border. Set true for the last item in a card. */
  noBorder?: boolean;
}

const TILE: Record<Category, { bg: string; emoji: string }> = {
  received: { bg: '#e6f6f8', emoji: '📥' },
  sent: { bg: '#eef3fb', emoji: '💸' },
  bill: { bg: '#fff0ef', emoji: '⚡' },
  airtime: { bg: '#e6f6f8', emoji: '📲' },
  reward: { bg: '#fff7e6', emoji: '🎁' },
  'reward-redeem': { bg: '#f3f5f8', emoji: '🛍️' },
  referral: { bg: '#eef0ff', emoji: '🤝' },
  generic: { bg: '#f3f5f8', emoji: '•' },
};

/** Single row of the activity list. */
export function ActivityRow({
  category,
  title,
  subtitle,
  amount,
  subAmount,
  positive,
  noBorder = false,
}: Props) {
  const tile = TILE[category];
  const isPositive =
    positive ?? (category === 'received' || category === 'reward' || category === 'referral');
  return (
    <XStack
      alignItems="center"
      gap={12}
      paddingVertical={13}
      borderBottomWidth={noBorder ? 0 : 1}
      borderBottomColor="rgba(1,46,84,0.06)"
    >
      <ClayIconTile size={42} radius={14} fill={tile.bg}>
        <Text fontSize={18}>{tile.emoji}</Text>
      </ClayIconTile>
      <YStack flex={1} gap={2}>
        <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#0c1b2a" numberOfLines={1}>
          {title}
        </Text>
        <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color="#8a98a6" numberOfLines={1}>
          {subtitle}
        </Text>
      </YStack>
      <YStack alignItems="flex-end" gap={2}>
        <Text
          fontFamily="PlusJakartaSans-ExtraBold"
          fontSize={14}
          color={isPositive ? '#1aa06b' : '#0c1b2a'}
        >
          {amount}
        </Text>
        {subAmount ? (
          <Text fontFamily="PlusJakartaSans-Medium" fontSize={10.5} color="#9aa7b5">
            {subAmount}
          </Text>
        ) : null}
      </YStack>
    </XStack>
  );
}
