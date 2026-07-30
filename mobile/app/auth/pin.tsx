/**
 * /auth/pin — returning-user PIN entry (Sasai Pay redesign).
 *
 * Navy gradient header with Sasai Pay wordmark; white body with masked
 * phone + PIN pip display + custom numeric keypad. On wrong PIN we shake
 * the pips and clear via `setPin('')`. Lockout is handled server-side;
 * we just surface a friendly screen on 429.
 */
import { useRef, useState } from 'react';
import { Animated } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { SasaiPayLogo } from '@/components/brand/SasaiPayLogo';
import { PinInput } from '@/components/forms/PinInput';
import { ClayButton } from '@/components/clay';
import { authPin } from '@/lib/api/auth';
import { ApiError, RateLimited } from '@/lib/api/errors';
import { getTenantId } from '@/lib/bootstrap';
import { setSessionToken } from '@/lib/storage';
import { maskPhone } from '@/lib/masking';

/** PIN entry for returning users. */
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
      Animated.timing(shake, { toValue: 12, duration: 50, useNativeDriver: true }),
      Animated.timing(shake, { toValue: -12, duration: 50, useNativeDriver: true }),
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
      setError(
        e instanceof ApiError ? 'Incorrect PIN. Try again.' : 'Something went wrong.',
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (lockedOut) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: '#ccd8e8' }}>
        <YStack flex={1} padding={26} gap="$4" alignItems="center" justifyContent="center">
          <Text
            fontFamily="PlusJakartaSans-ExtraBold"
            fontSize={24}
            color="#0c1b2a"
            textAlign="center"
          >
            Too many attempts
          </Text>
          <Text
            fontFamily="PlusJakartaSans-Regular"
            fontSize={14}
            color="#6a7888"
            textAlign="center"
          >
            For your safety we have temporarily blocked sign-in attempts.
            Try again in a few minutes.
          </Text>
          <View marginTop={12}>
            <ClayButton
              onPress={() => router.replace('/auth/phone')}
              fullWidth={false}
              height={50}
              accessibilityLabel="Use a different number"
            >
              <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#ffffff" paddingHorizontal={20}>
                Use a different number
              </Text>
            </ClayButton>
          </View>
        </YStack>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#ccd8e8' }} edges={['bottom']}>
      <YStack flex={1}>
        <GradientHeader paddingBottom={32}>
          <View paddingTop={16}>
            <SasaiPayLogo width={110} />
          </View>
        </GradientHeader>

        <YStack flex={1} padding={26} gap="$4" alignItems="center">
          <YStack gap={4} alignItems="center">
            <Text
              fontFamily="PlusJakartaSans-ExtraBold"
              fontSize={22}
              color="#0c1b2a"
              letterSpacing={-0.4}
            >
              Welcome back
            </Text>
            <Text
              fontFamily="PlusJakartaSans-Regular"
              fontSize={13}
              color="#6a7888"
            >
              Enter your PIN for {phone ? maskPhone(phone) : 'your account'}
            </Text>
          </YStack>

          <Animated.View
            style={{ transform: [{ translateX: shake }], marginTop: 18 }}
          >
            <PinInput
              value={pin}
              onChange={setPin}
              onComplete={onComplete}
              errored={!!error}
            />
          </Animated.View>

          {error ? (
            <Text
              fontFamily="PlusJakartaSans-Medium"
              color="#c0392b"
              fontSize={13}
              textAlign="center"
            >
              {error}
            </Text>
          ) : null}

          <View flex={1} />

          <XStack
            alignItems="center"
            gap={7}
            paddingBottom={6}
          >
            <Text fontSize={14}>🔒</Text>
            <Text
              fontFamily="PlusJakartaSans-Medium"
              fontSize={12.5}
              color="#8a98a6"
            >
              Secured with 256-bit encryption
            </Text>
          </XStack>
        </YStack>
      </YStack>
    </SafeAreaView>
  );
}
