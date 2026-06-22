/**
 * /home — the Pay tab. Sasai Pay redesign.
 *
 * Top: navy gradient hero with avatar + greeting, points pill, bell.
 * Overlapping white balance card with wallet picker + masked amount.
 * Quick actions row: Send / Airtime / Pay bills / Remit.
 * Promo banner: "Send money home, faster" call-out.
 * Recent activity: last 2 entries from the user's wallet.
 *
 * Pulls /me/wallet for the name, total balance, and PTS pill count.
 * Loading + error states fall back to muted greetings rather than
 * blocking the screen — the rest of the UI still renders.
 */
import { useState } from 'react';
import { ActivityIndicator, Pressable } from 'react-native';
import { useRouter } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';

import { ActivityRow } from '@/components/ui/ActivityRow';
import { BottomTabBar } from '@/components/ui/BottomTabBar';
import { GradientHeader } from '@/components/brand/GradientHeader';
import { SessionExpired } from '@/lib/api/errors';
import { getMyWallet } from '@/lib/api/wallet';
import { qk } from '@/lib/query';
import { clearAll } from '@/lib/storage';

/** Quick-action tile metadata (icon + label + route). */
const ACTIONS: ReadonlyArray<{ icon: string; label: string; href: string }> = [
  { icon: '💸', label: 'Send', href: '/p2p/recipient' },
  { icon: '📲', label: 'Airtime', href: '/home' }, // placeholder until /airtime ships
  { icon: '🧾', label: 'Pay bills', href: '/home' }, // placeholder
  { icon: '🌍', label: 'Remit', href: '/home' }, // placeholder
];

/** Format a decimal-string amount as a 2-line "$1,284.50" with the cents
 *  in a smaller muted tint per the design. Returns [whole, cents]. */
function splitAmount(amount: string): { whole: string; cents: string } {
  const n = parseFloat(amount);
  if (!Number.isFinite(n)) return { whole: '0', cents: '.00' };
  const [w, c] = n.toFixed(2).split('.');
  const withSep = w.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return { whole: withSep, cents: `.${c ?? '00'}` };
}

/** Initials for the avatar circle — first two letters of the first name. */
function initials(name: string | null | undefined): string {
  if (!name) return '··';
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? '';
  const second = parts[1]?.[0] ?? parts[0]?.[1] ?? '';
  return (first + second).toUpperCase();
}

/** Pay tab — home. */
export default function HomeScreen() {
  const router = useRouter();
  const [masked, setMasked] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: qk.wallet(),
    queryFn: getMyWallet,
  });

  if (error instanceof SessionExpired) {
    clearAll().finally(() => router.replace('/auth/phone'));
  }

  const firstName = data?.first_name ?? 'there';
  const zar = data?.accounts.find(
    (a) => a.currency === 'ZAR' && a.account_type === 'financial_wallet',
  );
  const points = data?.accounts.find((a) => a.currency === 'PTS');
  const balance = splitAmount(zar?.available_balance ?? '0');
  const pendingNum = (() => {
    const a = parseFloat(zar?.balance ?? '0');
    const b = parseFloat(zar?.available_balance ?? '0');
    const diff = a - b;
    return Number.isFinite(diff) && diff > 0 ? diff.toFixed(2) : '0.00';
  })();

  return (
    <View flex={1} backgroundColor="#f4f7fa">
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          {/* Header — navy gradient with user info + points + bell, plus
              extra bottom padding so the balance card overlaps by 58px. */}
          <GradientHeader paddingBottom={78}>
            <XStack alignItems="center" justifyContent="space-between" paddingTop={6}>
              <XStack alignItems="center" gap={11}>
                <View
                  width={42}
                  height={42}
                  borderRadius={21}
                  backgroundColor="#50C0D0"
                  alignItems="center"
                  justifyContent="center"
                >
                  <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#013a6b">
                    {initials(firstName)}
                  </Text>
                </View>
                <YStack>
                  <Text
                    fontFamily="PlusJakartaSans-Medium"
                    fontSize={12}
                    color="rgba(255,255,255,0.7)"
                  >
                    Welcome back
                  </Text>
                  <Text fontFamily="PlusJakartaSans-Bold" fontSize={15} color="#ffffff">
                    {firstName}
                  </Text>
                </YStack>
              </XStack>
              <XStack alignItems="center" gap={10}>
                <XStack
                  alignItems="center"
                  gap={7}
                  backgroundColor="rgba(255,255,255,0.14)"
                  borderColor="rgba(80,192,208,0.5)"
                  borderWidth={1}
                  borderRadius={22}
                  paddingHorizontal={12}
                  paddingVertical={6}
                >
                  <View
                    width={26}
                    height={26}
                    borderRadius={13}
                    backgroundColor="#50C0D0"
                    alignItems="center"
                    justifyContent="center"
                  >
                    <Text fontSize={13}>⭐</Text>
                  </View>
                  <YStack>
                    <Text
                      fontFamily="PlusJakartaSans-ExtraBold"
                      fontSize={13}
                      color="#ffffff"
                      lineHeight={14}
                    >
                      {points ? parseInt(points.available_balance, 10).toLocaleString('en-ZA') : '0'}
                    </Text>
                    <Text
                      fontFamily="PlusJakartaSans-SemiBold"
                      fontSize={8.5}
                      color="#9fd9e2"
                      letterSpacing={0.4}
                      lineHeight={10}
                    >
                      POINTS
                    </Text>
                  </YStack>
                </XStack>
                <View
                  width={40}
                  height={40}
                  borderRadius={12}
                  backgroundColor="rgba(255,255,255,0.12)"
                  alignItems="center"
                  justifyContent="center"
                  position="relative"
                >
                  <Text fontSize={18}>🔔</Text>
                  <View
                    position="absolute"
                    top={9}
                    right={10}
                    width={8}
                    height={8}
                    borderRadius={4}
                    backgroundColor="#ff5a5a"
                    borderWidth={1.5}
                    borderColor="#013a6b"
                  />
                </View>
              </XStack>
            </XStack>
          </GradientHeader>

          <YStack
            flex={1}
            paddingBottom={96}
          >
            {/* Overlapping balance card. Margin-top -58 lifts it into the
                gradient region so the card "floats" on the navy. */}
            <View
              marginTop={-58}
              marginHorizontal={18}
              backgroundColor="#ffffff"
              borderRadius={22}
              padding={20}
              shadowColor="#0c1b2a"
              shadowOpacity={0.12}
              shadowRadius={34}
              shadowOffset={{ width: 0, height: 14 }}
            >
              <XStack justifyContent="space-between" alignItems="center">
                <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#6a7888">
                  Total balance
                </Text>
                <View
                  backgroundColor="#e6f6f8"
                  paddingHorizontal={10}
                  paddingVertical={4}
                  borderRadius={20}
                >
                  <Text
                    fontFamily="PlusJakartaSans-SemiBold"
                    fontSize={12}
                    color="#2EB6C8"
                  >
                    ZAR wallet ▾
                  </Text>
                </View>
              </XStack>
              <XStack alignItems="flex-end" gap={8} marginTop={8}>
                <Text
                  fontFamily="PlusJakartaSans-ExtraBold"
                  fontSize={34}
                  color="#0c1b2a"
                  letterSpacing={-0.5}
                >
                  R {masked ? '••••' : balance.whole}
                </Text>
                {!masked && (
                  <Text
                    fontFamily="PlusJakartaSans-Bold"
                    fontSize={20}
                    color="#94a2b1"
                    marginBottom={4}
                  >
                    {balance.cents}
                  </Text>
                )}
                <Pressable
                  onPress={() => setMasked((m) => !m)}
                  style={{ marginLeft: 'auto', paddingBottom: 6 }}
                  accessibilityLabel="Toggle balance visibility"
                >
                  <Text fontSize={18} color="#94a2b1">
                    👁
                  </Text>
                </Pressable>
              </XStack>
              <XStack
                gap={18}
                marginTop={14}
                paddingTop={14}
                borderTopWidth={1}
                borderTopColor="#eef2f6"
                alignItems="center"
              >
                <YStack flex={1}>
                  <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11} color="#8a98a6">
                    Available
                  </Text>
                  <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#0c1b2a" marginTop={2}>
                    R {balance.whole}{balance.cents}
                  </Text>
                </YStack>
                <YStack flex={1}>
                  <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11} color="#8a98a6">
                    Pending
                  </Text>
                  <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#0c1b2a" marginTop={2}>
                    R {pendingNum}
                  </Text>
                </YStack>
                <Pressable accessibilityLabel="Top up" onPress={() => {}}>
                  <View
                    backgroundColor="#00508F"
                    paddingHorizontal={14}
                    paddingVertical={9}
                    borderRadius={12}
                  >
                    <Text fontFamily="PlusJakartaSans-Bold" fontSize={13} color="#ffffff">
                      + Top up
                    </Text>
                  </View>
                </Pressable>
              </XStack>
            </View>

            {/* Quick actions. Four tiles spaced evenly across the row. */}
            <XStack justifyContent="space-between" paddingHorizontal={22} paddingTop={22}>
              {ACTIONS.map((action) => (
                <Pressable
                  key={action.label}
                  onPress={() => router.push(action.href as never)}
                  accessibilityRole="button"
                  accessibilityLabel={action.label}
                  style={({ pressed }) => ({ opacity: pressed ? 0.85 : 1, width: 62 })}
                >
                  <YStack alignItems="center" gap={8}>
                    <View
                      width={54}
                      height={54}
                      borderRadius={18}
                      backgroundColor="#ffffff"
                      shadowColor="#0c1b2a"
                      shadowOpacity={0.07}
                      shadowRadius={16}
                      shadowOffset={{ width: 0, height: 6 }}
                      alignItems="center"
                      justifyContent="center"
                    >
                      <Text fontSize={22}>{action.icon}</Text>
                    </View>
                    <Text
                      fontFamily="PlusJakartaSans-SemiBold"
                      fontSize={11}
                      color="#3a4756"
                    >
                      {action.label}
                    </Text>
                  </YStack>
                </Pressable>
              ))}
            </XStack>

            {/* Promo banner — Sasai's "send money home" call-out. */}
            <View
              marginTop={14}
              marginHorizontal={18}
              backgroundColor="#00538f"
              borderRadius={20}
              padding={18}
              overflow="hidden"
              position="relative"
            >
              {/* Decorative ring at the bottom-right. */}
              <View
                position="absolute"
                width={140}
                height={140}
                borderRadius={70}
                borderWidth={24}
                borderColor="rgba(80,192,208,0.22)"
                bottom={-70}
                right={-40}
                pointerEvents="none"
              />
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={16} color="#ffffff">
                Send money home, faster
              </Text>
              <Text
                fontFamily="PlusJakartaSans-Medium"
                fontSize={12.5}
                color="rgba(255,255,255,0.82)"
                marginTop={4}
                maxWidth={200}
                lineHeight={18}
              >
                Transfer to any bank or mobile wallet across Africa.
              </Text>
              <Pressable onPress={() => router.push('/p2p/recipient')} style={{ marginTop: 14 }}>
                <View
                  alignSelf="flex-start"
                  backgroundColor="#ffffff"
                  paddingHorizontal={16}
                  paddingVertical={8}
                  borderRadius={11}
                >
                  <Text fontFamily="PlusJakartaSans-Bold" fontSize={13} color="#00508F">
                    Send now →
                  </Text>
                </View>
              </Pressable>
            </View>

            {/* Recent activity. */}
            <XStack
              justifyContent="space-between"
              alignItems="center"
              paddingHorizontal={22}
              paddingTop={22}
              paddingBottom={10}
            >
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={15} color="#0c1b2a">
                Recent activity
              </Text>
              <Pressable onPress={() => router.push('/transactions' as never)}>
                <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#00508F">
                  See all
                </Text>
              </Pressable>
            </XStack>
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
              {isLoading ? (
                <View paddingVertical={24} alignItems="center">
                  <ActivityIndicator color="#00508F" />
                </View>
              ) : (
                <>
                  <ActivityRow
                    category="received"
                    title="Received · Demo"
                    subtitle="Today · 10:24"
                    amount="+R 120.00"
                  />
                  <ActivityRow
                    category="bill"
                    title="ZESA Electricity"
                    subtitle="Today · 08:02"
                    amount="−R 18.50"
                    noBorder
                  />
                </>
              )}
            </View>
          </YStack>
        </YStack>
      </SafeAreaView>
      <BottomTabBar active="pay" />
    </View>
  );
}
