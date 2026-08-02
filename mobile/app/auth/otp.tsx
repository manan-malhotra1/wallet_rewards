/**
 * /auth/otp — six-box OTP entry with 30s resend countdown.
 *
 * Flow:
 *   1. Resends are gated by a 30s timer (`resendIn`).
 *   2. The boxes auto-submit when all six are filled.
 *   3. On 200 we cache the registration_token, then route to /auth/set-pin.
 *   4. On wrong OTP we shake the boxes and clear via `resetSignal`.
 *
 * In local dev (OTP_DEV_RETURN=true) the previous screen's OTP-send
 * response includes the code; we re-fetch a hint here on first mount so
 * a deep link or refresh still shows "Dev OTP: 123456".
 */
import { useEffect, useRef, useState } from 'react';
import {
  Animated,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  TouchableWithoutFeedback,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button, Text, XStack, YStack } from 'tamagui';

import { OtpInput } from '@/components/forms/OtpInput';
import { otpSend, otpVerify } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/errors';
import { getTenantId } from '@/lib/bootstrap';
import { setRegistrationToken } from '@/lib/storage';
import { useColors } from '@/lib/colors';

const RESEND_SECONDS = 30;

/** OTP verification screen. */
export default function OtpScreen() {
  const colors = useColors();
  const router = useRouter();
  const params = useLocalSearchParams<{ phone?: string }>();
  const phone = typeof params.phone === 'string' ? params.phone : '';

  const [resendIn, setResendIn] = useState(RESEND_SECONDS);
  const [devHint, setDevHint] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetTick, setResetTick] = useState(0);
  const shake = useRef(new Animated.Value(0)).current;

  // 30s resend countdown. Re-arms on each manual resend.
  useEffect(() => {
    if (resendIn <= 0) return;
    const id = setInterval(() => setResendIn((s) => s - 1), 1000);
    return () => clearInterval(id);
  }, [resendIn]);

  // Pull the dev OTP hint once on mount — refresh-friendly.
  useEffect(() => {
    if (!phone) return;
    let cancelled = false;
    (async () => {
      try {
        const tenantId = await getTenantId();
        const res = await otpSend(tenantId, phone);
        if (!cancelled && res.otp) setDevHint(res.otp);
      } catch {
        // Silently ignore — hint is a nice-to-have.
      }
    })();
    return () => {
      cancelled = true;
    };
    // Empty dep array — fire exactly once. Phone won't change mid-screen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function triggerShake() {
    Animated.sequence([
      Animated.timing(shake, { toValue: 10, duration: 50, useNativeDriver: true }),
      Animated.timing(shake, { toValue: -10, duration: 50, useNativeDriver: true }),
      Animated.timing(shake, { toValue: 8, duration: 50, useNativeDriver: true }),
      Animated.timing(shake, { toValue: 0, duration: 50, useNativeDriver: true }),
    ]).start();
  }

  async function handleComplete(otp: string) {
    if (submitting || !phone) return;
    setSubmitting(true);
    setError(null);
    try {
      const tenantId = await getTenantId();
      const res = await otpVerify(tenantId, phone, otp);
      await setRegistrationToken(res.registration_token);
      router.replace({ pathname: '/auth/set-pin', params: { phone } });
    } catch (e) {
      triggerShake();
      setResetTick((t) => t + 1);
      const msg =
        e instanceof ApiError
          ? 'Incorrect code, try again.'
          : 'Something went wrong. Try again.';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    if (resendIn > 0 || !phone) return;
    try {
      const tenantId = await getTenantId();
      const res = await otpSend(tenantId, phone);
      if (res.otp) setDevHint(res.otp);
      setResendIn(RESEND_SECONDS);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not resend code.');
    }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.screenBg }}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
          <ScrollView
            contentContainerStyle={{ flexGrow: 1 }}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            <YStack flex={1} padding="$5" gap="$4">
              <YStack gap="$2" marginTop="$4">
                <Text fontFamily="Inter-Bold" fontSize={26} color={colors.text}>
                  Verify your number
                </Text>
                <Text fontFamily="Inter-Regular" fontSize={14} color={colors.textMuted}>
                  We sent a 6-digit code to {phone}.
                </Text>
              </YStack>
              <Animated.View style={{ transform: [{ translateX: shake }] }}>
                <OtpInput onComplete={handleComplete} resetSignal={resetTick} />
              </Animated.View>
              {error ? (
                <Text fontFamily="Inter-Medium" color={colors.danger} fontSize={13} textAlign="center">
                  {error}
                </Text>
              ) : null}
              {devHint ? (
                <Text fontFamily="Inter-Regular" color={colors.textMuted} fontSize={12} textAlign="center">
                  Dev OTP: {devHint}
                </Text>
              ) : null}
              <XStack justifyContent="center">
                <Button
                  unstyled
                  disabled={resendIn > 0}
                  onPress={handleResend}
                  accessibilityLabel="Resend code"
                >
                  <Text
                    fontFamily="Inter-Medium"
                    fontSize={14}
                    color={resendIn > 0 ? colors.textMuted : colors.navy}
                  >
                    {resendIn > 0 ? `Resend code in ${resendIn}s` : 'Resend code'}
                  </Text>
                </Button>
              </XStack>
            </YStack>
          </ScrollView>
        </TouchableWithoutFeedback>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
