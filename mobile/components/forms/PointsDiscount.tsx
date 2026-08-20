/**
 * <PointsDiscount> — "pay part of this with points" on P2P and airtime.
 *
 * A toggle plus a points field. When on, the entered points are converted at
 * the tenant's configured rate and shown as a discount: the recipient still
 * gets the full amount, the wallet is only charged (amount − discount),
 * because the flow redeems the points into the wallet first (see
 * lib/api/redemption.ts).
 *
 * Renders NOTHING when the currency has no active rate, the user holds no
 * points, or no amount is entered yet — points are an optional sweetener, so
 * an unavailable one must not clutter the screen.
 *
 * The parent owns the state (`points`) so it can send it with the payment;
 * this component only enforces the ceiling (`maxRedeemablePoints`: balance,
 * both anti-drain caps, and the transaction amount).
 */
import { Pressable } from 'react-native';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { maxRedeemablePoints, pointsToFiat, type ConversionRate } from '@/lib/api/redemption';
import { formatMoney } from '@/lib/format';

interface Props {
  /** The tenant's active rate for this currency, or null when none exists. */
  rate: ConversionRate | null;
  /** The user's available points balance. */
  balance: number;
  /** The transaction amount being discounted (in `currency`). */
  txnAmount: number;
  /** Wallet currency the discount is credited in. */
  currency: string;
  /** Points the user has chosen to apply — 0 / null when the toggle is off. */
  points: number;
  /** Parent setter; receives 0 when the user switches the option off. */
  onChange: (points: number) => void;
}

/** Toggle + stepper for applying points to a transaction. */
export function PointsDiscount({
  rate,
  balance,
  txnAmount,
  currency,
  points,
  onChange,
}: Props) {
  const colors = useColors();

  // Nothing to offer: no rate for this currency, no points, or no amount yet.
  const max = rate ? maxRedeemablePoints({ balance, rate, txnAmount }) : 0;
  if (!rate || balance <= 0 || txnAmount <= 0 || max <= 0) return null;

  const enabled = points > 0;
  const discount = pointsToFiat(points, rate);
  const payable = Math.max(0, txnAmount - discount);

  /** Toggle on at the full allowance (the common case), or fully off. */
  function toggle() {
    onChange(enabled ? 0 : max);
  }

  /** Nudge the applied points, clamped to [0, max]. */
  function step(delta: number) {
    const next = Math.max(0, Math.min(max, points + delta));
    onChange(next);
  }

  return (
    <ClaySurface depth="soft" radius={16} padding={14} gap={10}>
      <Pressable
        onPress={toggle}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: enabled }}
        accessibilityLabel="Pay with points"
      >
        <XStack alignItems="center" gap={11}>
          <View
            width={22}
            height={22}
            borderRadius={6}
            borderWidth={2}
            borderColor={enabled ? colors.navy : colors.hairline}
            backgroundColor={enabled ? colors.navy : 'transparent'}
            alignItems="center"
            justifyContent="center"
          >
            {enabled ? <Ionicons name="checkmark" size={15} color={colors.textOnDark} /> : null}
          </View>
          <YStack flex={1} gap={2}>
            <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color={colors.text}>
              Pay with points
            </Text>
            <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color={colors.textMuted}>
              {balance.toLocaleString()} PTS available · up to {max.toLocaleString()} on this
              payment
            </Text>
          </YStack>
        </XStack>
      </Pressable>

      {enabled ? (
        <YStack gap={9}>
          {/* Stepper — points are whole units, so ± beats a keyboard here. */}
          <XStack alignItems="center" gap={10}>
            <Pressable
              onPress={() => step(-Math.max(1, Math.floor(max / 10)))}
              accessibilityLabel="Use fewer points"
              hitSlop={8}
            >
              <View
                width={34}
                height={34}
                borderRadius={17}
                backgroundColor={colors.clayInset}
                alignItems="center"
                justifyContent="center"
              >
                <Ionicons name="remove" size={18} color={colors.navy} />
              </View>
            </Pressable>
            <YStack flex={1} alignItems="center">
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={19} color={colors.text}>
                {points.toLocaleString()} PTS
              </Text>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color={colors.textMuted}>
                = {formatMoney(discount.toFixed(2), currency)} off
              </Text>
            </YStack>
            <Pressable
              onPress={() => step(Math.max(1, Math.floor(max / 10)))}
              accessibilityLabel="Use more points"
              hitSlop={8}
            >
              <View
                width={34}
                height={34}
                borderRadius={17}
                backgroundColor={colors.clayInset}
                alignItems="center"
                justifyContent="center"
              >
                <Ionicons name="add" size={18} color={colors.navy} />
              </View>
            </Pressable>
          </XStack>

          <XStack
            justifyContent="space-between"
            alignItems="center"
            paddingTop={9}
            borderTopWidth={1}
            borderTopColor={colors.hairline}
          >
            <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color={colors.textMuted}>
              You pay from your wallet
            </Text>
            <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={14.5} color={colors.text}>
              {formatMoney(payable.toFixed(2), currency)}
            </Text>
          </XStack>
        </YStack>
      ) : null}
    </ClaySurface>
  );
}
