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
import { formatZAR } from '@/lib/format';

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

/** Build "Received · 10:24" style subtitle for ActivityRow. */
function subtitleFor(t: WalletTransaction): string {
  const time = new Date(t.created_at).toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
  });
  const ref = transactionRef(t);
  // Surface the service charge inline so the deduction is explained — the
  // wallet was debited amount + fee, but the row's amount shows only the
  // transfer. ZAR fees only; PTS movements never carry a charge.
  const fee = parseFloat(t.fee_amount ?? '0');
  const feeNote = fee > 0 ? ` · Fee R ${fee.toFixed(2)}` : '';
  return `${ref} · ${time}${feeNote}`;
}

/** Format amount with sign + currency symbol. Returns ["+R 50.00", true]. */
function displayAmount(t: WalletTransaction): { text: string; positive: boolean } {
  const positive = t.direction === 'in';
  const sign = positive ? '+' : '−';
  if (t.currency === 'PTS') {
    return { text: `${sign}${Math.abs(parseFloat(t.amount)).toFixed(0)} PTS`, positive };
  }
  return { text: `${sign}R ${Math.abs(parseFloat(t.amount)).toFixed(2)}`, positive };
}

interface ChipProps {
  label: string;
  active: boolean;
  onPress: () => void;
}

function FilterChip({ label, active, onPress }: ChipProps) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>
      <View
        backgroundColor={active ? '#ffffff' : 'rgba(255,255,255,0.14)'}
        paddingHorizontal={14}
        paddingVertical={6}
        borderRadius={20}
      >
        <Text
          fontFamily={active ? 'PlusJakartaSans-Bold' : 'PlusJakartaSans-SemiBold'}
          fontSize={12}
          color={active ? '#00508F' : '#ffffff'}
        >
          {label}
        </Text>
      </View>
    </Pressable>
  );
}

/** Transactions list screen. */
export default function TransactionsScreen() {
  const [filter, setFilter] = useState<Filter>('all');
  const { data } = useQuery({ queryKey: qk.wallet(), queryFn: getMyWallet });
  const all = data?.recent_transactions ?? [];

  // Filtered transactions (drives the list + the summary totals).
  const filtered = useMemo(
    () => all.filter((t) => matchesFilter(t, filter)),
    [all, filter],
  );

  // Money in / out — sum amounts on ZAR txns (PTS doesn't belong on the
  // money strip). Computed from `all`, not `filtered`, so flipping the
  // filter doesn't change the headline numbers.
  const { moneyIn, moneyOut } = useMemo(() => {
    let inZ = 0;
    let outZ = 0;
    for (const t of all) {
      if (t.currency !== 'ZAR') continue;
      const n = Math.abs(parseFloat(t.amount));
      if (!Number.isFinite(n)) continue;
      if (t.direction === 'in') inZ += n;
      else outZ += n;
    }
    return { moneyIn: inZ, moneyOut: outZ };
  }, [all]);

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
    <View flex={1} backgroundColor="#ccd8e8">
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <GradientHeader paddingBottom={22}>
          <Text
            fontFamily="PlusJakartaSans-ExtraBold"
            fontSize={22}
            color="#ffffff"
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
              <Text fontSize={14} color="rgba(255,255,255,0.8)">🔍</Text>
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
              <Text fontSize={17}>⚙️</Text>
            </View>
          </XStack>
          <XStack gap={8} marginTop={14}>
            <FilterChip label="All" active={filter === 'all'} onPress={() => setFilter('all')} />
            <FilterChip label="Sent" active={filter === 'sent'} onPress={() => setFilter('sent')} />
            <FilterChip label="Received" active={filter === 'received'} onPress={() => setFilter('received')} />
            <FilterChip label="Bills" active={filter === 'bills'} onPress={() => setFilter('bills')} />
          </XStack>
        </GradientHeader>

        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingBottom: 110 }}
          showsVerticalScrollIndicator={false}
        >
          {/* Summary strip — money in vs out, computed from real data. */}
          <XStack gap={12} paddingHorizontal={18} paddingTop={16}>
            <ClaySurface depth="soft" radius={16} flex={1} padding={13}>
              <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11} color="#8a98a6">
                Money in
              </Text>
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={17} color="#1aa06b" marginTop={3}>
                +{formatZAR(moneyIn)}
              </Text>
            </ClaySurface>
            <ClaySurface depth="soft" radius={16} flex={1} padding={13}>
              <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11} color="#8a98a6">
                Money out
              </Text>
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={17} color="#c0392b" marginTop={3}>
                −{formatZAR(moneyOut)}
              </Text>
            </ClaySurface>
          </XStack>

          {groups.length === 0 ? (
            <YStack alignItems="center" paddingVertical={40}>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color="#8a98a6">
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
                  color="#8a98a6"
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
                        subtitle={subtitleFor(t)}
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
