/**
 * /transactions — full transactions list (Sasai Pay redesign).
 *
 * Navy gradient header with screen title + search field + filter chips.
 * Money in / Money out summary cards on the surface. Day-grouped rows
 * pulled from /me/wallet's recent_transactions for v0; pagination /
 * server-side history endpoint comes later.
 */
import { useMemo } from 'react';
import { ScrollView } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';

import { ActivityRow } from '@/components/ui/ActivityRow';
import { BottomTabBar } from '@/components/ui/BottomTabBar';
import { GradientHeader } from '@/components/brand/GradientHeader';
import { getMyWallet, WalletTransaction } from '@/lib/api/wallet';
import { qk } from '@/lib/query';

type Category = 'received' | 'sent' | 'bill' | 'airtime' | 'reward' | 'reward-redeem' | 'referral' | 'generic';

/** Heuristic: map backend transaction_type → display category. */
function categoryFor(t: WalletTransaction): Category {
  const ty = t.transaction_type?.toLowerCase() ?? '';
  if (ty.includes('reward')) return 'reward';
  if (ty.includes('redemption')) return 'reward-redeem';
  if (ty.includes('topup') || ty.includes('top_up') || ty.includes('top-up')) return 'received';
  if (t.currency === 'PTS') return 'reward';
  // Without a from/to comparison we can't tell sent from received
  // reliably; fall back to a generic icon and let the amount sign hint.
  return parseFloat(t.amount) >= 0 ? 'received' : 'sent';
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

/** Transactions list screen. */
export default function TransactionsScreen() {
  const { data } = useQuery({ queryKey: qk.wallet(), queryFn: getMyWallet });
  const txns = data?.recent_transactions ?? [];

  const groups = useMemo(() => {
    const byDay = new Map<string, WalletTransaction[]>();
    for (const t of txns) {
      const d = new Date(t.created_at);
      const key = dayLabel(d);
      if (!byDay.has(key)) byDay.set(key, []);
      byDay.get(key)!.push(t);
    }
    return Array.from(byDay.entries());
  }, [txns]);

  return (
    <View flex={1} backgroundColor="#f4f7fa">
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
            {['All', 'Sent', 'Received', 'Bills'].map((chip, i) => (
              <View
                key={chip}
                backgroundColor={i === 0 ? '#ffffff' : 'rgba(255,255,255,0.14)'}
                paddingHorizontal={14}
                paddingVertical={6}
                borderRadius={20}
              >
                <Text
                  fontFamily={i === 0 ? 'PlusJakartaSans-Bold' : 'PlusJakartaSans-SemiBold'}
                  fontSize={12}
                  color={i === 0 ? '#00508F' : '#ffffff'}
                >
                  {chip}
                </Text>
              </View>
            ))}
          </XStack>
        </GradientHeader>

        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingBottom: 110 }}
          showsVerticalScrollIndicator={false}
        >
          {/* Summary strip — money in vs out. */}
          <XStack gap={12} paddingHorizontal={18} paddingTop={16}>
            <View
              flex={1}
              backgroundColor="#ffffff"
              borderRadius={16}
              padding={13}
              shadowColor="#0c1b2a"
              shadowOpacity={0.05}
              shadowRadius={16}
              shadowOffset={{ width: 0, height: 6 }}
            >
              <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11} color="#8a98a6">
                Money in
              </Text>
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={17} color="#1aa06b" marginTop={3}>
                +R 640.00
              </Text>
            </View>
            <View
              flex={1}
              backgroundColor="#ffffff"
              borderRadius={16}
              padding={13}
              shadowColor="#0c1b2a"
              shadowOpacity={0.05}
              shadowRadius={16}
              shadowOffset={{ width: 0, height: 6 }}
            >
              <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11} color="#8a98a6">
                Money out
              </Text>
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={17} color="#0c1b2a" marginTop={3}>
                −R 312.80
              </Text>
            </View>
          </XStack>

          {groups.length === 0 ? (
            <YStack alignItems="center" paddingVertical={40}>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color="#8a98a6">
                No activity yet.
              </Text>
            </YStack>
          ) : (
            groups.map(([day, items]) => (
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
                <View
                  marginHorizontal={18}
                  backgroundColor="#ffffff"
                  borderRadius={18}
                  paddingHorizontal={14}
                  shadowColor="#0c1b2a"
                  shadowOpacity={0.05}
                  shadowRadius={16}
                  shadowOffset={{ width: 0, height: 6 }}
                >
                  {items.map((t, i) => {
                    const amount = parseFloat(t.amount);
                    const sign = amount >= 0 ? '+' : '−';
                    const display =
                      t.currency === 'PTS'
                        ? `${sign}${Math.abs(amount).toFixed(0)} PTS`
                        : `${sign}R ${Math.abs(amount).toFixed(2)}`;
                    return (
                      <ActivityRow
                        key={t.id}
                        category={categoryFor(t)}
                        title={t.transaction_type ?? 'Transaction'}
                        subtitle={new Date(t.created_at).toLocaleTimeString('en-GB', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                        amount={display}
                        noBorder={i === items.length - 1}
                      />
                    );
                  })}
                </View>
              </YStack>
            ))
          )}
        </ScrollView>
      </SafeAreaView>
      <BottomTabBar active="transactions" />
    </View>
  );
}
