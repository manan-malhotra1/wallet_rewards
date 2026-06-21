/**
 * /home — placeholder home screen for the bootstrap dispatch.
 *
 * Pulls /me/wallet to confirm the session works, greets the user by first
 * name, and offers a sign-out button. Real home + P2P land in dispatch 2.
 *
 * If the wallet fetch returns 401 (session_expired or invalid bearer) we
 * clear local state and redirect to /auth/phone — no retry, no prompt.
 */
import { useEffect } from 'react';
import { ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button, Text, View, YStack } from 'tamagui';

import { getMyWallet } from '@/lib/api/wallet';
import { SessionExpired } from '@/lib/api/errors';
import { qk } from '@/lib/query';
import { signOut } from '@/lib/auth';
import { clearAll } from '@/lib/storage';

/** Placeholder home — greet + sign-out. */
export default function HomeScreen() {
  const router = useRouter();
  const { data, isLoading, error } = useQuery({
    queryKey: qk.wallet(),
    queryFn: getMyWallet,
  });

  // Session-expired = clear and bounce. Any other error renders inline.
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
          <Button marginTop="$3" onPress={onSignOut}>
            Sign out
          </Button>
        </YStack>
      </SafeAreaView>
    );
  }

  const firstName = data?.first_name ?? 'there';

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
      <YStack flex={1} padding="$5" gap="$3">
        <YStack gap="$2" marginTop="$5">
          <Text fontFamily="Inter-Bold" fontSize={28} color="$ink">
            Hi {firstName},
          </Text>
          <Text fontFamily="Inter-Regular" fontSize={16} color="$muted">
            You're signed in.
          </Text>
        </YStack>
        <View flex={1} />
        <Button
          size="$5"
          theme="active"
          backgroundColor="$sasaiNavy"
          color="white"
          onPress={onSignOut}
          accessibilityLabel="Sign out"
        >
          Sign out
        </Button>
      </YStack>
    </SafeAreaView>
  );
}
