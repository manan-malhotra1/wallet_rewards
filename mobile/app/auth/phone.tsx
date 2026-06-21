/**
 * /auth/phone — country code + phone number entry.
 *
 * On Continue:
 *   1. Resolve tenant_id via the bootstrap call (cached in memory)
 *   2. Call /auth/start to see if the phone is registered
 *   3. needs_pin → cache phone, route to /auth/pin
 *      needs_otp → cache phone, fire /otp/send, route to /auth/otp
 *
 * We persist the phone in secure-store on success so /auth/otp + /auth/pin
 * can recover it from a deep link or app restart.
 */
import { useState } from 'react';
import { ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { Button, Text, View, YStack } from 'tamagui';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PhoneInput } from '@/components/forms/PhoneInput';
import { authStart, otpSend } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/errors';
import { getTenantId } from '@/lib/bootstrap';
import { setLastPhone } from '@/lib/storage';

/** Phone entry screen — the entry point of the auth flow. */
export default function PhoneScreen() {
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
      await setLastPhone(phone);
      if (status === 'needs_pin') {
        router.push({ pathname: '/auth/pin', params: { phone } });
        return;
      }
      // needs_otp — fire /otp/send and forward
      await otpSend(tenantId, phone);
      router.push({ pathname: '/auth/otp', params: { phone } });
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : 'Something went wrong. Try again.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
      <YStack flex={1} padding="$5" gap="$4">
        <YStack gap="$2" marginTop="$4">
          <Text fontFamily="Inter-Bold" fontSize={28} color="$ink">
            Welcome to Sasai
          </Text>
          <Text fontFamily="Inter-Regular" fontSize={15} color="$muted">
            Enter your phone number to sign in or create an account.
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
          accessibilityLabel="Continue"
        >
          {loading ? <ActivityIndicator color="#FFFFFF" /> : 'Continue'}
        </Button>
      </YStack>
    </SafeAreaView>
  );
}
