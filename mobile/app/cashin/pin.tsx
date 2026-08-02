/**
 * /cashin/pin — authorise the cash-in with a PIN (step-up).
 *
 * Step 3 of the cash-in flow (mirrors /cashout/pin). Reached only when the
 * backend demanded step-up (401 `step_up_required`) on the amount screen. We
 * replay cashIn() with the SAME idempotency key carried in params + the PIN.
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
import { useColors } from '@/lib/colors';
import { InvalidStepUpPin } from '@/lib/api/errors';
import { cashIn, cashInFailureReason, newCashInIdempotencyKey } from '@/lib/api/cashin';
import { qk } from '@/lib/query';
import { formatMoney, maskPhone } from '@/lib/format';

/** Confirm cash-in with PIN screen. */
export default function CashInPinScreen() {
  const router = useRouter();
  const colors = useColors();
  const qc = useQueryClient();
  const params = useLocalSearchParams<{
    phone?: string;
    amount?: string;
    currency?: string;
    idem?: string;
  }>();
  const customerPhone = typeof params.phone === 'string' ? params.phone : '';
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
      : newCashInIdempotencyKey(),
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
      const res = await cashIn({
        customerPhone,
        amount,
        currency,
        pin: entered,
        idempotencyKey: idemRef.current,
      });
      await qc.invalidateQueries({ queryKey: qk.wallet() });
      router.replace({
        pathname: '/cashin/success',
        params: {
          phone: customerPhone,
          amount: res.amount,
          fee: res.fee,
          commission: res.commission,
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
        pathname: '/cashin/failed',
        params: { phone: customerPhone, amount, currency, reason: cashInFailureReason(e) },
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          <GradientHeader paddingBottom={22}>
            <HeaderBack title="Confirm cash-in" />
            <StepIndicator step={3} caption="Step 3 of 3 · Authorise this cash-in" />
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
            <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color={colors.textMuted}>
              You are funding
            </Text>
            <Text
              fontFamily="PlusJakartaSans-ExtraBold"
              fontSize={34}
              color={colors.text}
              marginTop={4}
              letterSpacing={-0.5}
            >
              {formatMoney(amount, currency)}
            </Text>
            <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color={colors.textMuted} marginTop={4}>
              to customer{' '}
              <Text fontFamily="PlusJakartaSans-Bold" color={colors.text}>
                {maskPhone(customerPhone)}
              </Text>
            </Text>
          </ClaySurface>

          {/* PIN entry + encryption note. */}
          <YStack flex={1} alignItems="center" justifyContent="center" gap={22}>
            <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color={colors.text}>
              Enter your PIN to authorise
            </Text>
            <Animated.View style={{ transform: [{ translateX: shake }] }}>
              <PinInput value={pin} onChange={setPin} onComplete={onComplete} errored={!!error} />
            </Animated.View>
            {error ? (
              <Text
                fontFamily="PlusJakartaSans-Medium"
                color={colors.danger}
                fontSize={13}
                textAlign="center"
              >
                {error}
              </Text>
            ) : (
              <XStack alignItems="center" gap={7}>
                <Ionicons name="lock-closed" size={14} color={colors.textMuted} />
                <Text fontFamily="PlusJakartaSans-Medium" fontSize={12.5} color={colors.textMuted}>
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
