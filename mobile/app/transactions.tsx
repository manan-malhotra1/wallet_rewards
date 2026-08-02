/**
 * /transactions — full transactions list (Sasai Pay redesign).
 *
 * Navy gradient header with screen title + search field + filter chips
 * (All / Sent / Received / Bills — interactive). Money in / Money out
 * cards compute totals from the actual transactions for the current
 * month. Day-grouped rows pulled from /me/wallet's recent_transactions;
 * each row uses the new backend-supplied direction + counterparty_name
 * fields so debits render in red ink and credits in green.
 */
import { Pressable } from 'react-native';
import { useMemo, useState } from 'react';
import { ScrollView } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { ActivityRow } from '@/components/ui/ActivityRow';
import { BottomTabBar } from '@/components/ui/BottomTabBar';
import { GradientHeader } from '@/components/brand/GradientHeader';
import { ClaySurface } from '@/components/clay';
import {
  activityCategory,
  getMyWallet,
  transactionRef,
  transactionTitle,
  WalletTransaction,
} from '@/lib/api/wallet';
import { qk } from '@/lib/query';
import { formatMoney } from '@/lib/format';
import { useColors } from '@/lib/colors';

type Filter = 'all' | 'sent' | 'received' | 'bills';

/** Returns true when the transaction matches the active filter. */
function matchesFilter(t: WalletTransaction, filter: Filter): boolean {
  if (filter === 'all') return true;
  if (filter === 'sent') return t.direction === 'out' && t.transaction_type === 'p2p';
  if (filter === 'received') return t.direction === 'in';
  // "Bills" is a placeholder for now — once bill-pay ships it'll match
  // `transaction_type === 'bill_payment'` (or similar). Empty for v0.
  if (filter === 'bills') return false;
  return true;
}

/** Format a Date as "Today", "Yesterday", or "DD MMM". */
function dayLabel(d: Date): string {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = Math.round((today.getTime() - target.getTime()) / 86_400_000);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Yesterday';
  return target.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}

/**
 * Build the "time · Fee R2.00 · Tax …" meta line for ActivityRow. The reference
 * (`S_2026…`) is passed separately as the row's `subtitle`, so the long ref and
 * the time/charges live on different lines and neither truncates the other.
 *
 * Surfaces the per-user charges/earnings from THIS user's perspective — the
 * backend already scopes these: `fee_amount`/`tax_amount` are "0" unless you
 * paid them, and `commission_amount` is non-"0" only for the agent who earned
 * it. Each is in the transaction's own currency; PTS movements carry no charge.
 */
function metaFor(t: WalletTransaction): string {
  const time = new Date(t.created_at).toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
  });
  const fee = parseFloat(t.fee_amount ?? '0');
  const tax = parseFloat(t.tax_amount ?? '0');
  const commission = parseFloat(t.commission_amount ?? '0');
  const feeNote = fee > 0 ? ` · Fee ${formatMoney(fee, t.currency)}` : '';
  const taxNote = tax > 0 ? ` · Tax ${formatMoney(tax, t.currency)}` : '';
  const commissionNote =
    commission > 0 ? ` · Commission ${formatMoney(commission, t.currency)}` : '';
  return `${time}${feeNote}${taxNote}${commissionNote}`;
}

/**
 * Format amount with sign in the transaction's OWN currency (ZAR, INR, …),
 * or as points for PTS rows. Returns e.g. ["+₹ 50.00", true].
 */
function displayAmount(t: WalletTransaction): { text: string; positive: boolean } {
  const positive = t.direction === 'in';
  const sign = positive ? '+' : '−';
  if (t.currency === 'PTS') {
    return { text: `${sign}${Math.abs(parseFloat(t.amount)).toFixed(0)} PTS`, positive };
  }
  return { text: `${sign}${formatMoney(Math.abs(parseFloat(t.amount)), t.currency)}`, positive };
}

interface ChipProps {
  label: string;
  active: boolean;
  onPress: () => void;
}

function FilterChip({ label, active, onPress }: ChipProps) {
  const colors = useColors();
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>
      <View
        backgroundColor={active ? colors.clayRaised : 'rgba(255,255,255,0.14)'}
        paddingHorizontal={14}
        paddingVertical={6}
        borderRadius={20}
      >
        <Text
          fontFamily={active ? 'PlusJakartaSans-Bold' : 'PlusJakartaSans-SemiBold'}
          fontSize={12}
          color={active ? colors.navy : colors.textOnDark}
        >
          {label}
        </Text>
      </View>
    </Pressable>
  );
}

/** Transactions list screen. */
export default function TransactionsScreen() {
  const colors = useColors();
  const [filter, setFilter] = useState<Filter>('all');
  // Which wallet currency the list + money strip are scoped to. Null until the
  // user taps a chip; the effective `currency` below then falls back to ZAR (or
  // the first wallet). Money is NEVER summed across currencies, so the strip is
  // always single-currency.
  const [currencyFilter, setCurrencyFilter] = useState<string | null>(null);
  const { data } = useQuery({ queryKey: qk.wallet(), queryFn: getMyWallet });
  const all = data?.recent_transactions ?? [];

  // Financial-wallet currencies drive the currency chip row (INR must be
  // reachable, not just ZAR).
  const currencies = (data?.accounts ?? [])
    .filter((a) => a.account_type === 'financial_wallet')
    .map((a) => a.currency);
  const currency =
    currencyFilter ?? (currencies.includes('ZAR') ? 'ZAR' : currencies[0] ?? 'ZAR');

  // Filtered transactions (drives the list + the summary totals). Scoped to the
  // selected currency; PTS reward/redemption rows are kept regardless since
  // points aren't a spendable currency tied to any wallet.
  const filtered = useMemo(
    () =>
      all.filter(
        (t) =>
          (t.currency === currency || t.currency === 'PTS') && matchesFilter(t, filter),
      ),
    [all, filter, currency],
  );

  // Money in / out — sum amounts on the selected currency only (PTS doesn't
  // belong on the money strip, and currencies are never summed together).
  // Computed from `all`, not `filtered`, so flipping the type filter doesn't
  // change the headline numbers.
  const { moneyIn, moneyOut } = useMemo(() => {
    let inN = 0;
    let outN = 0;
    for (const t of all) {
      if (t.currency !== currency) continue;
      const n = Math.abs(parseFloat(t.amount));
      if (!Number.isFinite(n)) continue;
      if (t.direction === 'in') inN += n;
      else outN += n;
    }
    return { moneyIn: inN, moneyOut: outN };
  }, [all, currency]);

  // Day-grouped rendering, preserving original sort order (newest first).
  const groups = useMemo(() => {
    const result: { day: string; items: WalletTransaction[] }[] = [];
    const dayIndex = new Map<string, number>();
    for (const t of filtered) {
      const day = dayLabel(new Date(t.created_at));
      const idx = dayIndex.get(day);
      if (idx === undefined) {
        dayIndex.set(day, result.length);
        result.push({ day, items: [t] });
      } else {
        result[idx].items.push(t);
      }
    }
    return result;
  }, [filtered]);

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <GradientHeader paddingBottom={22}>
          <Text
            fontFamily="PlusJakartaSans-ExtraBold"
            fontSize={22}
            color={colors.textOnDark}
            marginTop={6}
          >
            Transactions
          </Text>
          <XStack gap={10} marginTop={16}>
            <View
              flex={1}
              height={44}
              borderRadius={13}
              backgroundColor="rgba(255,255,255,0.14)"
              paddingHorizontal={13}
              flexDirection="row"
              alignItems="center"
              gap={9}
            >
              <Ionicons name="search" size={17} color="rgba(255,255,255,0.8)" />
              <Text
                fontFamily="PlusJakartaSans-Medium"
                fontSize={13.5}
                color="rgba(255,255,255,0.8)"
              >
                Search transactions
              </Text>
            </View>
            <View
              width={44}
              height={44}
              borderRadius={13}
              backgroundColor="rgba(255,255,255,0.14)"
              alignItems="center"
              justifyContent="center"
            >
              <Ionicons name="options-outline" size={20} color={colors.textOnDark} />
            </View>
          </XStack>
          <XStack gap={8} marginTop={14}>
            <FilterChip label="All" active={filter === 'all'} onPress={() => setFilter('all')} />
            <FilterChip label="Sent" active={filter === 'sent'} onPress={() => setFilter('sent')} />
            <FilterChip label="Received" active={filter === 'received'} onPress={() => setFilter('received')} />
            <FilterChip label="Bills" active={filter === 'bills'} onPress={() => setFilter('bills')} />
          </XStack>
          {/* Currency scope — only meaningful with more than one wallet. Picks
              which currency the list + money strip show; each is single-currency
              so money is never summed across currencies. */}
          {currencies.length > 1 ? (
            <XStack gap={8} marginTop={10}>
              {currencies.map((c) => (
                <FilterChip
                  key={c}
                  label={c}
                  active={currency === c}
                  onPress={() => setCurrencyFilter(c)}
                />
              ))}
            </XStack>
          ) : null}
        </GradientHeader>

        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingBottom: 110 }}
          showsVerticalScrollIndicator={false}
        >
          {/* Summary strip — money in vs out, computed from real data. */}
          <XStack gap={12} paddingHorizontal={18} paddingTop={16}>
            <ClaySurface depth="soft" radius={16} flex={1} padding={13}>
              <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11} color={colors.textMuted}>
                Money in
              </Text>
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={17} color={colors.success} marginTop={3}>
                +{formatMoney(moneyIn, currency)}
              </Text>
            </ClaySurface>
            <ClaySurface depth="soft" radius={16} flex={1} padding={13}>
              <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11} color={colors.textMuted}>
                Money out
              </Text>
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={17} color={colors.danger} marginTop={3}>
                −{formatMoney(moneyOut, currency)}
              </Text>
            </ClaySurface>
          </XStack>

          {groups.length === 0 ? (
            <YStack alignItems="center" paddingVertical={40}>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color={colors.textMuted}>
                {filter === 'all'
                  ? 'No activity yet.'
                  : `No ${filter} transactions yet.`}
              </Text>
            </YStack>
          ) : (
            groups.map(({ day, items }) => (
              <YStack key={day}>
                <Text
                  fontFamily="PlusJakartaSans-Bold"
                  fontSize={12}
                  color={colors.textMuted}
                  textTransform="uppercase"
                  letterSpacing={0.8}
                  paddingHorizontal={22}
                  paddingTop={18}
                  paddingBottom={8}
                >
                  {day}
                </Text>
                <ClaySurface
                  depth="soft"
                  radius={18}
                  marginHorizontal={18}
                  paddingHorizontal={14}
                >
                  {items.map((t, i) => {
                    const amt = displayAmount(t);
                    return (
                      <ActivityRow
                        key={t.id}
                        category={activityCategory(t)}
                        title={transactionTitle(t)}
                        subtitle={transactionRef(t)}
                        meta={metaFor(t)}
                        amount={amt.text}
                        positive={amt.positive}
                        noBorder={i === items.length - 1}
                      />
                    );
                  })}
                </ClaySurface>
              </YStack>
            ))
          )}
        </ScrollView>
      </SafeAreaView>
      <BottomTabBar active="transactions" />
    </View>
  );
}
