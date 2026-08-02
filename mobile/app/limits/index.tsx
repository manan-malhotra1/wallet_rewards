/**
 * /limits — the current user's send & receive limits (Sasai Pay).
 *
 * Navy gradient header + a clay body. For each currency wallet the backend
 * returns, we render a "Send" and a "Receive" section, each with Daily /
 * Weekly / Monthly rows. A row shows the value consumed against its cap as a
 * small progress bar plus the money figures (via `formatMoney`) and the
 * transaction count ("3 / 10 transactions"). When a cap axis is null we show
 * "No limit" and only the consumed figure — no bar.
 *
 * Data comes from GET /me/limits (see lib/api/limits.ts). Money is never
 * summed across currencies — each currency block stands alone.
 */
import { ScrollView } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { ClaySurface } from '@/components/clay';
import { getMyLimits, type LimitAxis, type LimitWindows, type MyLimits } from '@/lib/api/limits';
import { qk } from '@/lib/query';
import { formatMoney } from '@/lib/format';

/** Human label + key for each rolling window, in display order. */
const WINDOWS: ReadonlyArray<{ key: keyof LimitWindows; label: string }> = [
  { key: 'daily', label: 'Daily' },
  { key: 'weekly', label: 'Weekly' },
  { key: 'monthly', label: 'Monthly' },
];

/**
 * Fraction of an axis's value cap that's been consumed, clamped to [0, 1].
 *
 * Returns null when there is no value cap (nothing to fill). Guards against a
 * zero/invalid cap so the bar never divides by zero or overflows its track.
 */
function valueFraction(axis: LimitAxis): number | null {
  if (axis.cap_value == null) return null;
  const cap = parseFloat(axis.cap_value);
  const used = parseFloat(axis.consumed_value);
  if (!Number.isFinite(cap) || cap <= 0) return null;
  const frac = used / cap;
  if (!Number.isFinite(frac)) return 0;
  return Math.max(0, Math.min(1, frac));
}

/** Thin clay-inset progress track with a navy fill at `fraction` (0–1). */
function ProgressBar({ fraction }: { fraction: number }) {
  return (
    <View
      height={7}
      borderRadius={4}
      backgroundColor="#dbe4ee"
      overflow="hidden"
      marginTop={8}
    >
      <View
        height={7}
        borderRadius={4}
        // Near-full bars tint amber as a soft "approaching your limit" cue.
        backgroundColor={fraction >= 0.85 ? '#c98a00' : '#00508F'}
        width={`${Math.round(fraction * 100)}%`}
      />
    </View>
  );
}

/**
 * A single window row (e.g. "Daily") within a Send/Receive section.
 *
 * Capped axis → value figures ("R 3,000.00 / R 10,000.00") + a progress bar +
 * the count line. Uncapped axis → "No limit" and just the consumed figure, no
 * bar (there's nothing to fill toward).
 */
function LimitRow({
  label,
  axis,
  currency,
  noBorder,
}: {
  label: string;
  axis: LimitAxis;
  currency: string;
  noBorder: boolean;
}) {
  const fraction = valueFraction(axis);
  const consumed = formatMoney(axis.consumed_value, currency);
  const capped = axis.cap_value != null;

  // Count line — omit the cap when there's no count limit.
  const countLine =
    axis.cap_count != null
      ? `${axis.consumed_count} / ${axis.cap_count} transactions`
      : `${axis.consumed_count} transactions`;

  return (
    <YStack
      paddingVertical={12}
      borderBottomWidth={noBorder ? 0 : 1}
      borderBottomColor="rgba(1,46,84,0.06)"
    >
      <XStack alignItems="center" justifyContent="space-between">
        <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color="#0c1b2a">
          {label}
        </Text>
        {capped ? (
          <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#3a4756">
            {consumed} / {formatMoney(axis.cap_value as string, currency)}
          </Text>
        ) : (
          <Text fontFamily="PlusJakartaSans-Bold" fontSize={12.5} color="#1aa06b">
            No limit
          </Text>
        )}
      </XStack>

      {fraction != null ? <ProgressBar fraction={fraction} /> : null}

      <XStack alignItems="center" justifyContent="space-between" marginTop={6}>
        <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color="#8a98a6">
          {countLine}
        </Text>
        {!capped ? (
          <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color="#8a98a6">
            {consumed} used
          </Text>
        ) : null}
      </XStack>
    </YStack>
  );
}

/** A "Send" or "Receive" section: a titled clay card of three window rows. */
function DirectionSection({
  title,
  windows,
  currency,
}: {
  title: string;
  windows: LimitWindows;
  currency: string;
}) {
  return (
    <YStack gap={8}>
      <Text
        fontFamily="PlusJakartaSans-Bold"
        fontSize={12}
        color="#8a98a6"
        textTransform="uppercase"
        letterSpacing={0.8}
        paddingHorizontal={4}
      >
        {title}
      </Text>
      <ClaySurface depth="soft" radius={18} paddingHorizontal={16} paddingVertical={2}>
        {WINDOWS.map((w, i) => (
          <LimitRow
            key={w.key}
            label={w.label}
            axis={windows[w.key]}
            currency={currency}
            noBorder={i === WINDOWS.length - 1}
          />
        ))}
      </ClaySurface>
    </YStack>
  );
}

/** All limits for one currency wallet — a heading + Send + Receive sections. */
function CurrencyBlock({ limits }: { limits: MyLimits }) {
  return (
    <YStack gap={16}>
      <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={16} color="#0c1b2a" paddingHorizontal={4}>
        {limits.currency} wallet
      </Text>
      <DirectionSection title="Send" windows={limits.send} currency={limits.currency} />
      <DirectionSection title="Receive" windows={limits.receive} currency={limits.currency} />
    </YStack>
  );
}

/** Limits screen. */
export default function LimitsScreen() {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.limits(),
    queryFn: getMyLimits,
  });

  const blocks = data ?? [];

  return (
    <View flex={1} backgroundColor="#ccd8e8">
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <GradientHeader paddingBottom={24}>
          <HeaderBack title="Limits" />
          <Text
            fontFamily="PlusJakartaSans-Medium"
            fontSize={12.5}
            color="rgba(255,255,255,0.85)"
            marginTop={10}
          >
            How much you can send and receive across each window.
          </Text>
        </GradientHeader>

        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingHorizontal: 18, paddingTop: 18, paddingBottom: 40 }}
          showsVerticalScrollIndicator={false}
        >
          {isLoading ? (
            <YStack alignItems="center" paddingVertical={40}>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color="#5a6b7b">
                Loading your limits…
              </Text>
            </YStack>
          ) : isError ? (
            <YStack alignItems="center" paddingVertical={40}>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color="#c0392b">
                Couldn't load your limits. Pull back and try again.
              </Text>
            </YStack>
          ) : blocks.length === 0 ? (
            <YStack alignItems="center" paddingVertical={40}>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color="#5a6b7b">
                No limits to show yet.
              </Text>
            </YStack>
          ) : (
            <YStack gap={26}>
              {blocks.map((b) => (
                <CurrencyBlock key={b.currency} limits={b} />
              ))}
            </YStack>
          )}
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}
