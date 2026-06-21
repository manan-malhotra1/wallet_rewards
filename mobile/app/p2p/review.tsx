/**
 * /p2p/review — confirm + send.
 *
 * Single tap on "Send" fires POST /payments/p2p via the step-up-aware
 * helper in `lib/api/payments.ts`. If the backend demands a PIN, the
 * PinChallengeSheet slides up; the helper handles the wrong-PIN retry
 * loop internally so this screen just provides a fresh PIN each time it's
 * asked, with a `prevError` hint to drive the inline error display.
 *
 * On success the wallet query is invalidated and we route to /p2p/success.
 */
import { useState } from 'react';
import { ActivityIndicator } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Text, View, XStack, YStack } from 'tamagui';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PinChallengeSheet } from '@/components/ui/PinChallengeSheet';
import { sendP2P } from '@/lib/api/payments';
import { ApiError, InvalidStepUpPin } from '@/lib/api/errors';
import { qk } from '@/lib/query';
import { formatZAR, maskPhone } from '@/lib/format';

/** Review + Send screen. */
export default function ReviewScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const params = useLocalSearchParams<{ phone: string; amount: string }>();
  const recipientPhone = typeof params.phone === 'string' ? params.phone : '';
  const amount = typeof params.amount === 'string' ? params.amount : '0';

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Step-up sheet state. The promise resolver is stashed so the API helper
  // can await user input from inside its retry loop.
  const [sheetOpen, setSheetOpen] = useState(false);
  const [pinError, setPinError] = useState<string | null>(null);
  const [attemptKey, setAttemptKey] = useState(0);
  const [pinResolver, setPinResolver] = useState<((pin: string | null) => void) | null>(
    null,
  );

  function askForPin(prevError: ApiError | null): Promise<string | null> {
    setPinError(
      prevError instanceof InvalidStepUpPin ? 'Incorrect PIN. Try again.' : null,
    );
    if (prevError instanceof InvalidStepUpPin) {
      // Force the keypad to remount so the user starts with empty pips.
      setAttemptKey((k) => k + 1);
    }
    setSheetOpen(true);
    return new Promise((resolve) => {
      setPinResolver(() => resolve);
    });
  }

  function onPinSubmit(pin: string) {
    if (pinResolver) {
      pinResolver(pin);
      setPinResolver(null);
    }
  }

  function onPinCancel() {
    setSheetOpen(false);
    if (pinResolver) {
      pinResolver(null);
      setPinResolver(null);
    }
  }

  async function onSend() {
    setBusy(true);
    setError(null);
    try {
      const result = await sendP2P({ recipientPhone, amount }, askForPin);
      await qc.invalidateQueries({ queryKey: qk.wallet() });
      setSheetOpen(false);
      router.replace({
        pathname: '/p2p/success',
        params: {
          phone: recipientPhone,
          amount,
          earned: String(result.earned_points ?? 0),
        },
      });
    } catch (e) {
      setSheetOpen(false);
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : 'Send failed. Try again.';
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
      <YStack flex={1} padding="$5" gap="$5">
        <Text fontFamily="Inter-Bold" fontSize={26} color="$ink" marginTop="$4">
          Review
        </Text>

        <YStack
          backgroundColor="rgba(20,73,137,0.05)"
          padding="$4"
          borderRadius={16}
          gap="$1"
        >
          <Text fontFamily="Inter-Medium" fontSize={13} color="$muted">
            To
          </Text>
          <Text fontFamily="Inter-SemiBold" fontSize={17} color="$ink">
            {maskPhone(recipientPhone)}
          </Text>
        </YStack>

        <YStack alignItems="center" gap="$2" marginTop="$3">
          <Text fontFamily="Inter-Bold" fontSize={48} color="$sasaiNavy">
            {formatZAR(amount)}
          </Text>
          <Text fontFamily="Inter-Regular" fontSize={13} color="$muted">
            Fee R 0.00
          </Text>
        </YStack>

        <XStack
          justifyContent="space-between"
          backgroundColor="rgba(20,73,137,0.05)"
          padding="$4"
          borderRadius={16}
        >
          <Text fontFamily="Inter-Medium" fontSize={13} color="$muted">
            From
          </Text>
          <Text fontFamily="Inter-Medium" fontSize={13} color="$ink">
            ZAR Wallet
          </Text>
        </XStack>

        {error ? (
          <Text fontFamily="Inter-Medium" color="$error" fontSize={13}>
            {error}
          </Text>
        ) : null}

        <View flex={1} />

        <Button
          size="$5"
          theme="active"
          backgroundColor="$sasaiNavy"
          color="white"
          disabled={busy}
          opacity={busy ? 0.7 : 1}
          onPress={onSend}
          accessibilityLabel={`Send ${formatZAR(amount)}`}
        >
          {busy ? <ActivityIndicator color="#FFFFFF" /> : `Send ${formatZAR(amount)}`}
        </Button>

        <PinChallengeSheet
          open={sheetOpen}
          onCancel={onPinCancel}
          onSubmit={onPinSubmit}
          error={pinError}
          attemptKey={attemptKey}
        />
      </YStack>
    </SafeAreaView>
  );
}
