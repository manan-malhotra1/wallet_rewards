/**
 * /limits — the current user's send & receive limits (Sasai Pay).
 *
 * Navy gradient header + a clay body. A currency filter (chips) picks WHICH
 * wallet's limits are shown — one currency at a time instead of stacked
 * blocks. `?currency=` preselects a chip (the home-screen limit banner deep-
 * links here with the exhausted currency).
 *
 * Each Send/Receive section renders Daily / Weekly / Monthly rows. A row
 * shows TWO progress bars — value consumed and transactions consumed — so a
 * count-exhausted limit (e.g. 15/15 sends at 5% of the value cap) is as
 * loud as a value-exhausted one: full bars go red with a "Limit reached"
 * badge. Uncapped dimensions show "No limit" and no bar.
 *
 * Data comes from GET /me/limits (see lib/api/limits.ts). Money is never
 * summed across currencies — each currency block stands alone.
 */
import { useEffect, useState } from 'react';
import { Pressable, ScrollView } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
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
 * Fraction of a consumed/cap pair, clamped to [0, 1]. Returns null when there
 * is no cap (nothing to fill) or the cap is zero/invalid (never divide by 0).
 */
function fractionOf(consumed: number, cap: number | null): number | null {
  if (cap == null || !Number.isFinite(cap) || cap <= 0) return null;
  const frac = consumed / cap;
  if (!Number.isFinite(frac)) return 0;
  return Math.max(0, Math.min(1, frac));
}

/**
 * One captioned progress bar. Fill color escalates with consumption:
 * navy → amber at 85% ("approaching") → red at 100% ("limit reached").
 */
function ProgressBar({ caption, fraction }: { caption: string; fraction: number }) {
  const colors = useColors();
  const fill = fraction >= 1 ? colors.danger : fraction >= 0.85 ? colors.warning : colors.navy;
  return (
    <XStack alignItems="center" gap={8} marginTop={7}>
      <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={10} color={colors.textFaint} width={40}>
        {caption}
      </Text>
      <View flex={1} height={7} borderRadius={4} backgroundColor={colors.clayInset} overflow="hidden">
        <View
          height={7}
          borderRadius={4}
          backgroundColor={fill}
          width={`${Math.round(fraction * 100)}%`}
        />
      </View>
    </XStack>
  );
}

/** Small red badge shown on a row whose count or value cap is fully used. */
function LimitReachedBadge() {
  const colors = useColors();
  return (
    <View backgroundColor="#fdeef0" paddingHorizontal={8} paddingVertical={3} borderRadius={10}>
      <Text fontFamily="PlusJakartaSans-Bold" fontSize={10.5} color={colors.danger}>
        Limit reached
      </Text>
    </View>
  );
}

/**
 * A single window row (e.g. "Daily") within a Send/Receive section.
 *
 * Renders the value figures + value bar AND the count figures + count bar, so
 * whichever dimension exhausts first is visibly the blocker (red bar + badge +
 * red figures). Uncapped dimensions render "No limit"/plain counts, no bar.
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
  const colors = useColors();
  const valueFrac = fractionOf(
    parseFloat(axis.consumed_value),
    axis.cap_value != null ? parseFloat(axis.cap_value) : null,
  );
  const countFrac = fractionOf(axis.consumed_count, axis.cap_count);
  const valueFull = valueFrac != null && valueFrac >= 1;
  const countFull = countFrac != null && countFrac >= 1;

  const consumed = formatMoney(axis.consumed_value, currency);
  const countLine =
    axis.cap_count != null
      ? `${axis.consumed_count} / ${axis.cap_count} transactions`
      : `${axis.consumed_count} transactions`;

  return (
    <YStack
      paddingVertical={12}
      borderBottomWidth={noBorder ? 0 : 1}
      borderBottomColor={colors.hairline}
    >
      <XStack alignItems="center" justifyContent="space-between" gap={8}>
        <XStack alignItems="center" gap={8}>
          <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color={colors.text}>
            {label}
          </Text>
          {valueFull || countFull ? <LimitReachedBadge /> : null}
        </XStack>
        {axis.cap_value != null ? (
          <Text
            fontFamily="PlusJakartaSans-SemiBold"
            fontSize={12.5}
            color={valueFull ? colors.danger : colors.textMuted}
          >
            {consumed} / {formatMoney(axis.cap_value, currency)}
          </Text>
        ) : (
          <Text fontFamily="PlusJakartaSans-Bold" fontSize={12.5} color={colors.success}>
            No limit
          </Text>
        )}
      </XStack>

      {valueFrac != null ? <ProgressBar caption="Value" fraction={valueFrac} /> : null}
      {countFrac != null ? <ProgressBar caption="Count" fraction={countFrac} /> : null}

      <XStack alignItems="center" justifyContent="space-between" marginTop={6}>
        <Text
          fontFamily={countFull ? 'PlusJakartaSans-Bold' : 'PlusJakartaSans-Medium'}
          fontSize={11.5}
          color={countFull ? colors.danger : colors.textMuted}
        >
          {countLine}
        </Text>
        {axis.cap_value == null ? (
          <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color={colors.textMuted}>
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
  const colors = useColors();
  return (
    <YStack gap={8}>
      <Text
        fontFamily="PlusJakartaSans-Bold"
        fontSize={12}
        color={colors.textMuted}
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

/** Pill row that picks which currency wallet's limits are displayed. */
function CurrencyFilter({
  currencies,
  selected,
  onSelect,
}: {
  currencies: string[];
  selected: string;
  onSelect: (c: string) => void;
}) {
  const colors = useColors();
  return (
    <XStack gap={8} flexWrap="wrap">
      {currencies.map((c) => {
        const active = c === selected;
        return (
          <Pressable
            key={c}
            onPress={() => onSelect(c)}
            accessibilityRole="button"
            accessibilityLabel={`Show ${c} limits`}
          >
            <View
              paddingHorizontal={18}
              paddingVertical={9}
              borderRadius={20}
              backgroundColor={active ? colors.navy : colors.rim}
              borderWidth={1.5}
              borderColor={active ? colors.navy : colors.hairline}
            >
              <Text
                fontFamily="PlusJakartaSans-Bold"
                fontSize={13}
                color={active ? colors.textOnDark : colors.navy}
              >
                {c}
              </Text>
            </View>
          </Pressable>
        );
      })}
    </XStack>
  );
}

/** Limits screen — one currency at a time, picked via the filter chips. */
export default function LimitsScreen() {
  const colors = useColors();
  const params = useLocalSearchParams<{ currency?: string }>();
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.limits(),
    queryFn: getMyLimits,
  });

  const blocks = data ?? [];
  const currencies = blocks.map((b) => b.currency);
  const [selected, setSelected] = useState<string | null>(null);

  // Resolve the active chip once data lands: honour ?currency= (the home
  // banner deep-links with the exhausted currency), else the first wallet.
  useEffect(() => {
    if (currencies.length === 0 || (selected && currencies.includes(selected))) return;
    const fromParam =
      typeof params.currency === 'string' && currencies.includes(params.currency)
        ? params.currency
        : null;
    setSelected(fromParam ?? currencies[0]);
  }, [currencies, selected, params.currency]);

  const active: MyLimits | undefined = blocks.find((b) => b.currency === selected) ?? blocks[0];

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
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
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color={colors.textMuted}>
                Loading your limits…
              </Text>
            </YStack>
          ) : isError ? (
            <YStack alignItems="center" paddingVertical={40}>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color={colors.danger}>
                Couldn't load your limits. Pull back and try again.
              </Text>
            </YStack>
          ) : !active ? (
            <YStack alignItems="center" paddingVertical={40}>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color={colors.textMuted}>
                No limits to show yet.
              </Text>
            </YStack>
          ) : (
            <YStack gap={16}>
              {currencies.length > 1 ? (
                <CurrencyFilter
                  currencies={currencies}
                  selected={active.currency}
                  onSelect={setSelected}
                />
              ) : null}
              <DirectionSection title="Send" windows={active.send} currency={active.currency} />
              <DirectionSection
                title="Receive"
                windows={active.receive}
                currency={active.currency}
              />
            </YStack>
          )}
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}
