/**
 * /cashout/pin — authorise the cash-out with a PIN (step-up).
 *
 * Step 3 of the cash-out flow (mirrors /p2p/pin). Reached only when the
 * backend demanded step-up (401 `step_up_required`) on the amount screen. We
 * replay cashOut() with the SAME idempotency key carried in params + the PIN.
 * A wrong PIN (401 `invalid_step_up_pin`) shakes the pips and clears them for
 * a retry under the same key; other failures route to the failure screen.
 */
import { useRef, useState } from 'react';
import { Animated } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { StepIndicator } from '@/components/brand/StepIndicator';
import { PinInput } from '@/components/forms/PinInput';
import { ClaySurface } from '@/components/clay';
import { InvalidStepUpPin } from '@/lib/api/errors';
import { cashOut, cashOutFailureReason, newCashOutIdempotencyKey } from '@/lib/api/cashout';
import { qk } from '@/lib/query';
import { formatMoney, maskPhone } from '@/lib/format';

/** Confirm cash-out with PIN screen. */
export default function CashOutPinScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const params = useLocalSearchParams<{
    phone?: string;
    amount?: string;
    currency?: string;
    idem?: string;
  }>();
  const agentPhone = typeof params.phone === 'string' ? params.phone : '';
  const amount = typeof params.amount === 'string' ? params.amount : '0';
  const currency = typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';

  const [pin, setPin] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shake = useRef(new Animated.Value(0)).current;
  // Idempotency key persists across wrong-PIN retries so the backend dedups
  // correctly (any rejection happens pre-ledger). It is forwarded from the
  // amount screen's step-up branch so the no-PIN attempt and the with-PIN
  // retry share one logical transaction.
  const idemRef = useRef(
    typeof params.idem === 'string' && params.idem.length > 0
      ? params.idem
      : newCashOutIdempotencyKey(),
  );

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
      const res = await cashOut({
        agentPhone,
        amount,
        currency,
        pin: entered,
        idempotencyKey: idemRef.current,
      });
      await qc.invalidateQueries({ queryKey: qk.wallet() });
      router.replace({
        pathname: '/cashout/success',
        params: {
          phone: agentPhone,
          amount: res.amount,
          fee: res.fee,
          currency,
          reference: (res.reference ?? res.transaction_id).slice(0, 8).toUpperCase(),
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
      router.replace({
        pathname: '/cashout/failed',
        params: { phone: agentPhone, amount, currency, reason: cashOutFailureReason(e) },
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <View flex={1} backgroundColor="#ccd8e8">
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          <GradientHeader paddingBottom={22}>
            <HeaderBack title="Confirm cash-out" />
            <StepIndicator step={3} caption="Step 3 of 3 · Authorise your cash-out" />
          </GradientHeader>

          {/* Summary card. */}
          <ClaySurface
            depth="raised"
            radius={20}
            marginHorizontal={18}
            marginTop={18}
            padding={18}
            alignItems="center"
          >
            <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#8a98a6">
              You are cashing out
            </Text>
            <Text
              fontFamily="PlusJakartaSans-ExtraBold"
              fontSize={34}
              color="#0c1b2a"
              marginTop={4}
              letterSpacing={-0.5}
            >
              {formatMoney(amount, currency)}
            </Text>
            <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color="#5a6b7b" marginTop={4}>
              to agent{' '}
              <Text fontFamily="PlusJakartaSans-Bold" color="#0c1b2a">
                {maskPhone(agentPhone)}
              </Text>
            </Text>
          </ClaySurface>

          {/* PIN entry + encryption note. */}
          <YStack flex={1} alignItems="center" justifyContent="center" gap={22}>
            <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#0c1b2a">
              Enter your PIN to authorise
            </Text>
            <Animated.View style={{ transform: [{ translateX: shake }] }}>
              <PinInput value={pin} onChange={setPin} onComplete={onComplete} errored={!!error} />
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
            ) : (
              <XStack alignItems="center" gap={7}>
                <Ionicons name="lock-closed" size={14} color="#8a98a6" />
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
