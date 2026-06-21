/**
 * /auth/pin — returning-user PIN entry.
 *
 * Flow:
 *   1. User types a 4-digit PIN via the in-screen keypad.
 *   2. We call /auth/pin with (tenant, phone, pin).
 *   3. On 200 we persist session_token and navigate to /home.
 *   4. On invalid_pin → shake + clear + error label.
 *   5. On 429 (lockout) → friendly "Too many attempts" screen.
 *
 * Lockout state is fully owned by the backend. We just surface it.
 */
import { useRef, useState } from 'react';
import { ActivityIndicator, Animated } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button, Text, YStack } from 'tamagui';

import { PinInput } from '@/components/forms/PinInput';
import { authPin } from '@/lib/api/auth';
import { ApiError, RateLimited } from '@/lib/api/errors';
import { getTenantId } from '@/lib/bootstrap';
import { setSessionToken } from '@/lib/storage';
import { maskPhone } from '@/lib/masking';

/** PIN entry for users who already have a wallet. */
export default function PinScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ phone?: string }>();
  const phone = typeof params.phone === 'string' ? params.phone : '';

  const [pin, setPin] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lockedOut, setLockedOut] = useState(false);
  const shake = useRef(new Animated.Value(0)).current;

  function triggerShake() {
    Animated.sequence([
      Animated.timing(shake, { toValue: 10, duration: 50, useNativeDriver: true }),
      Animated.timing(shake, { toValue: -10, duration: 50, useNativeDriver: true }),
      Animated.timing(shake, { toValue: 8, duration: 50, useNativeDriver: true }),
      Animated.timing(shake, { toValue: 0, duration: 50, useNativeDriver: true }),
    ]).start();
  }

  async function onComplete(entered: string) {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const tenantId = await getTenantId();
      const { session_token } = await authPin(tenantId, phone, entered);
      await setSessionToken(session_token);
      router.replace('/home');
    } catch (e) {
      triggerShake();
      setPin('');
      if (e instanceof RateLimited) {
        setLockedOut(true);
        return;
      }
      const msg =
        e instanceof ApiError ? 'Incorrect PIN, try again.' : 'Something went wrong.';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  if (lockedOut) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
        <YStack flex={1} padding="$5" gap="$4" alignItems="center" justifyContent="center">
          <Text fontFamily="Inter-Bold" fontSize={24} color="$ink" textAlign="center">
            Too many attempts
          </Text>
          <Text fontFamily="Inter-Regular" fontSize={14} color="$muted" textAlign="center">
            For your safety we have temporarily blocked sign-in attempts.
            Try again in a few minutes.
          </Text>
          <Button
            marginTop="$4"
            size="$5"
            theme="active"
            backgroundColor="$sasaiNavy"
            color="white"
            onPress={() => router.replace('/auth/phone')}
            accessibilityLabel="Back to phone entry"
          >
            Use a different number
          </Button>
        </YStack>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
      <YStack flex={1} padding="$5" gap="$5">
        <YStack gap="$2" marginTop="$4">
          <Text fontFamily="Inter-Bold" fontSize={26} color="$ink">
            Welcome back
          </Text>
          <Text fontFamily="Inter-Regular" fontSize={14} color="$muted">
            Enter your PIN for {phone ? maskPhone(phone) : 'your account'}.
          </Text>
        </YStack>
        <Animated.View style={{ transform: [{ translateX: shake }] }}>
          <PinInput
            value={pin}
            onChange={setPin}
            onComplete={onComplete}
            label="Enter PIN"
            errored={!!error}
          />
        </Animated.View>
        {error ? (
          <Text fontFamily="Inter-Medium" color="$error" fontSize={13} textAlign="center">
            {error}
          </Text>
        ) : null}
        {submitting ? (
          <YStack alignItems="center">
            <ActivityIndicator color="#144989" />
          </YStack>
        ) : null}
      </YStack>
    </SafeAreaView>
  );
}
