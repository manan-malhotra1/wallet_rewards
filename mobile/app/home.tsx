/**
 * /home — wallet balance + Send Money entry point.
 *
 * Pulls /me/wallet to render a hero card with the user's ZAR available
 * balance, plus a "Send Money" CTA that pushes the P2P flow. PTS balance
 * is shown as a quiet pill in the header. This is the minimal home for
 * the login + P2P demo — the full home (action chips, beneficiary strip,
 * featured campaign, activity preview) lives in the design spec but isn't
 * scoped for this build.
 *
 * Session-expired errors clear local state and bounce to /auth/phone.
 */
import { useEffect } from 'react';
import { ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button, Text, View, XStack, YStack } from 'tamagui';

import { getMyWallet, type WalletAccount } from '@/lib/api/wallet';
import { SessionExpired } from '@/lib/api/errors';
import { qk } from '@/lib/query';
import { signOut } from '@/lib/auth';
import { clearAll } from '@/lib/storage';
import { formatPTS, formatZAR } from '@/lib/format';

/** Pick the ZAR financial wallet from an account list (or undefined). */
function findZarAccount(accounts: WalletAccount[] | undefined): WalletAccount | undefined {
  return accounts?.find(
    (a) => a.currency === 'ZAR' && a.account_type === 'financial_wallet',
  );
}

/** Pick the PTS points account (or undefined). */
function findPtsAccount(accounts: WalletAccount[] | undefined): WalletAccount | undefined {
  return accounts?.find(
    (a) => a.currency === 'PTS' && a.account_type === 'points_account',
  );
}

/** Authenticated home — wallet card + Send Money + Sign out. */
export default function HomeScreen() {
  const router = useRouter();
  const { data, isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: qk.wallet(),
    queryFn: getMyWallet,
  });

  // Session-expired = clear + bounce. Any other error renders inline.
  useEffect(() => {
    if (error instanceof SessionExpired) {
      (async () => {
        await clearAll();
        router.replace('/auth/phone');
      })();
    }
  }, [error, router]);

  async function onSignOut() {
    await signOut();
    router.replace('/auth/phone');
  }

  if (isLoading) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
        <YStack flex={1} alignItems="center" justifyContent="center">
          <ActivityIndicator color="#144989" size="large" />
        </YStack>
      </SafeAreaView>
    );
  }

  if (error && !(error instanceof SessionExpired)) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
        <YStack flex={1} padding="$5" gap="$3" alignItems="center" justifyContent="center">
          <Text fontFamily="Inter-Bold" fontSize={20} color="$ink">
            Could not load wallet
          </Text>
          <Text fontFamily="Inter-Regular" fontSize={13} color="$muted" textAlign="center">
            {error instanceof Error ? error.message : 'Unknown error'}
          </Text>
          <Button marginTop="$3" onPress={() => refetch()}>
            {isRefetching ? <ActivityIndicator color="#144989" /> : 'Retry'}
          </Button>
          <Button onPress={onSignOut} backgroundColor="transparent" color="$muted">
            Sign out
          </Button>
        </YStack>
      </SafeAreaView>
    );
  }

  const firstName = data?.first_name ?? 'there';
  const zar = findZarAccount(data?.accounts);
  const pts = findPtsAccount(data?.accounts);
  const ptsBalance = pts ? parseInt(pts.balance, 10) || 0 : 0;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
      <YStack flex={1} padding="$5" gap="$5">
        {/* Top row — greeting on the left, PTS pill on the right. */}
        <XStack alignItems="center" justifyContent="space-between" marginTop="$2">
          <Text fontFamily="Inter-Bold" fontSize={22} color="$ink">
            Hi {firstName}
          </Text>
          {ptsBalance > 0 ? (
            <XStack
              backgroundColor="rgba(72,194,207,0.18)"
              paddingHorizontal="$3"
              paddingVertical="$2"
              borderRadius={16}
            >
              <Text fontFamily="Inter-SemiBold" fontSize={13} color="$sasaiNavy">
                {formatPTS(ptsBalance)}
              </Text>
            </XStack>
          ) : null}
        </XStack>

        {/* Balance hero card. */}
        <YStack
          backgroundColor="$sasaiNavy"
          padding="$5"
          borderRadius={24}
          gap="$2"
        >
          <Text fontFamily="Inter-Medium" fontSize={13} color="rgba(255,255,255,0.85)">
            ZAR · Available
          </Text>
          <Text fontFamily="Inter-Bold" fontSize={40} color="white">
            {zar ? formatZAR(zar.available_balance) : 'R 0.00'}
          </Text>
          <Text fontFamily="Inter-Regular" fontSize={12} color="rgba(255,255,255,0.7)" marginTop="$1">
            sasai · wallet
          </Text>
        </YStack>

        {/* Quick action — Send Money. */}
        <Button
          size="$5"
          theme="active"
          backgroundColor="$sasaiTeal"
          color="$sasaiNavy"
          onPress={() => router.push('/p2p/recipient')}
          accessibilityLabel="Send money"
        >
          <Text fontFamily="Inter-SemiBold" fontSize={16} color="$sasaiNavy">
            Send money
          </Text>
        </Button>

        <View flex={1} />

        <Button
          size="$4"
          backgroundColor="transparent"
          color="$muted"
          onPress={onSignOut}
          accessibilityLabel="Sign out"
        >
          Sign out
        </Button>
      </YStack>
    </SafeAreaView>
  );
}
