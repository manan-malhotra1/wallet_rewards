/**
 * /p2p/pin — confirm payment with PIN (Sasai Pay redesign).
 *
 * Step 3 of the send-money flow. Gradient header w/ step indicator,
 * payment-summary card (amount + recipient), centered PIN pip display
 * with encryption note, and the PIN keypad at the bottom (with a
 * biometric icon slot for v2). On 4 digits we fire /payments/p2p with
 * the same idempotency key. Wrong PIN clears the dots and shows an
 * inline error; lockout / other errors route to /p2p/failed; success
 * routes to /p2p/success with receipt data.
 */
import { useRef, useState } from 'react';
import { Animated } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { StepIndicator } from '@/components/brand/StepIndicator';
import { PinInput } from '@/components/forms/PinInput';
import { newIdempotencyKey } from '@/lib/api/client';
import { ApiError, InvalidStepUpPin, RateLimited } from '@/lib/api/errors';
import { sendP2P } from '@/lib/api/payments';
import { qk } from '@/lib/query';
import { maskPhone } from '@/lib/format';

/** Confirm with PIN screen. */
export default function PinConfirmScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const params = useLocalSearchParams<{ phone: string; amount: string }>();
  const recipientPhone = typeof params.phone === 'string' ? params.phone : '';
  const amount = typeof params.amount === 'string' ? params.amount : '0';

  const [pin, setPin] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shake = useRef(new Animated.Value(0)).current;
  // Idempotency key persists across wrong-PIN retries so the backend
  // dedups correctly (any rejection happens pre-ledger).
  const idemRef = useRef(newIdempotencyKey());

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
      const res = await sendP2P({
        recipientPhone,
        amount,
        pin: entered,
        idempotencyKey: idemRef.current,
      });
      await qc.invalidateQueries({ queryKey: qk.wallet() });
      router.replace({
        pathname: '/p2p/success',
        params: {
          phone: recipientPhone,
          amount,
          earned: String(res.earned_points ?? 0),
          reference: res.transaction_id.slice(0, 8).toUpperCase(),
        },
      });
    } catch (e) {
      triggerShake();
      setPin('');
      if (e instanceof InvalidStepUpPin) {
        setError('Incorrect PIN. Try again.');
        setSubmitting(false);
        return;
      }
      const reason =
        e instanceof RateLimited
          ? 'Too many attempts. Try again later.'
          : e instanceof ApiError
            ? e.message
            : 'Payment failed.';
      router.replace({
        pathname: '/p2p/failed' as never,
        params: { phone: recipientPhone, amount, reason },
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <View flex={1} backgroundColor="#f4f7fa">
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          <GradientHeader paddingBottom={22}>
            <HeaderBack title="Confirm payment" />
            <StepIndicator step={3} caption="Step 3 of 3 · Authorise your payment" />
          </GradientHeader>

          {/* Summary card */}
          <View
            marginHorizontal={18}
            marginTop={18}
            backgroundColor="#ffffff"
            borderRadius={18}
            padding={18}
            shadowColor="#0c1b2a"
            shadowOpacity={0.05}
            shadowRadius={16}
            shadowOffset={{ width: 0, height: 6 }}
            alignItems="center"
          >
            <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#8a98a6">
              You are sending
            </Text>
            <Text
              fontFamily="PlusJakartaSans-ExtraBold"
              fontSize={34}
              color="#0c1b2a"
              marginTop={4}
              letterSpacing={-0.5}
            >
              R {parseFloat(amount).toFixed(2)}
            </Text>
            <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color="#5a6b7b" marginTop={4}>
              to{' '}
              <Text fontFamily="PlusJakartaSans-Bold" color="#0c1b2a">
                {maskPhone(recipientPhone)}
              </Text>
            </Text>
          </View>

          {/* PIN entry + encryption note */}
          <YStack flex={1} alignItems="center" justifyContent="center" gap={22}>
            <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#0c1b2a">
              Enter your PIN to authorise
            </Text>
            <Animated.View style={{ transform: [{ translateX: shake }] }}>
              <PinInput
                value={pin}
                onChange={setPin}
                onComplete={onComplete}
                errored={!!error}
              />
            </Animated.View>
            {error ? (
              <Text fontFamily="PlusJakartaSans-Medium" color="#c0392b" fontSize={13} textAlign="center">
                {error}
              </Text>
            ) : (
              <XStack alignItems="center" gap={7}>
                <Text fontSize={14}>🔒</Text>
                <Text fontFamily="PlusJakartaSans-Medium" fontSize={12.5} color="#8a98a6">
                  Secured with 256-bit encryption
                </Text>
              </XStack>
            )}
          </YStack>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
