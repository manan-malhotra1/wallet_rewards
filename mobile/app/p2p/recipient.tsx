/**
 * /p2p/recipient — pick who you're sending to (by phone number).
 *
 * Re-uses `/auth/start` as a lookup probe: a phone that returns `needs_otp`
 * isn't a registered Sasai user yet, so we reject with a friendly inline
 * error rather than letting the P2P call fail server-side. This shaves a
 * round-trip and gives a tighter error message.
 */
import { useState } from 'react';
import { ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { Button, Text, View, YStack } from 'tamagui';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PhoneInput } from '@/components/forms/PhoneInput';
import { authStart } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/errors';
import { getTenantId } from '@/lib/bootstrap';

/** Send-money recipient picker — phone number entry. */
export default function RecipientScreen() {
  const router = useRouter();
  const [phone, setPhone] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canContinue = phone.replace(/\D/g, '').length >= 9 && !loading;

  async function onContinue() {
    setLoading(true);
    setError(null);
    try {
      const tenantId = await getTenantId();
      const { status } = await authStart(tenantId, phone);
      if (status === 'needs_otp') {
        // Not a registered user yet — short-circuit before /payments/p2p.
        setError("That number isn't on Sasai yet.");
        return;
      }
      router.push({ pathname: '/p2p/amount', params: { phone } });
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : 'Lookup failed. Try again.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
      <YStack flex={1} padding="$5" gap="$4">
        <YStack gap="$2" marginTop="$4">
          <Text fontFamily="Inter-Bold" fontSize={26} color="$ink">
            Send money
          </Text>
          <Text fontFamily="Inter-Regular" fontSize={15} color="$muted">
            Who are you sending to?
          </Text>
        </YStack>
        <View marginTop="$2">
          <PhoneInput onChange={setPhone} />
        </View>
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
          disabled={!canContinue}
          opacity={canContinue ? 1 : 0.5}
          onPress={onContinue}
          accessibilityLabel="Continue to amount"
        >
          {loading ? <ActivityIndicator color="#FFFFFF" /> : 'Continue'}
        </Button>
      </YStack>
    </SafeAreaView>
  );
}
