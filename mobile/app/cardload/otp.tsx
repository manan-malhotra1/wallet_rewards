/**
 * /cardload/otp — step 2 of the simulated card top-up: "3-D Secure" OTP.
 *
 * SIMULATOR: no code is actually sent — the accepted OTP is hardcoded to
 * 123456 (shown as a demo hint). Wrong codes shake and clear, mirroring
 * the auth OTP screen. Success replaces into the processing screen so the
 * user can't back into a re-submit.
 */
import { useEffect, useRef, useState } from 'react';
import { Animated, Keyboard, KeyboardAvoidingView, Platform, ScrollView, TouchableWithoutFeedback } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button, Text, View, XStack, YStack } from 'tamagui';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { StepIndicator } from '@/components/brand/StepIndicator';
import { OtpInput } from '@/components/forms/OtpInput';
import { useColors } from '@/lib/colors';

/** The simulator's only accepted verification code. */
const SIM_OTP = '123456';
const RESEND_SECONDS = 30;

/** Card-verification OTP — step 2 of 3. */
export default function CardLoadOtpScreen() {
  const colors = useColors();
  const router = useRouter();
  const params = useLocalSearchParams<{ last4?: string; amount?: string; currency?: string }>();
  const last4 = typeof params.last4 === 'string' ? params.last4 : '';
  const amount = typeof params.amount === 'string' ? params.amount : '0';
  const currency = typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';

  const [error, setError] = useState<string | null>(null);
  const [resetTick, setResetTick] = useState(0);
  const [resendIn, setResendIn] = useState(RESEND_SECONDS);
  const shake = useRef(new Animated.Value(0)).current;

  // Cosmetic resend countdown — nothing is actually sent in the simulator.
  useEffect(() => {
    if (resendIn <= 0) return;
    const id = setInterval(() => setResendIn((s) => s - 1), 1000);
    return () => clearInterval(id);
  }, [resendIn]);

  function triggerShake() {
    Animated.sequence([
      Animated.timing(shake, { toValue: 10, duration: 50, useNativeDriver: true }),
      Animated.timing(shake, { toValue: -10, duration: 50, useNativeDriver: true }),
      Animated.timing(shake, { toValue: 8, duration: 50, useNativeDriver: true }),
      Animated.timing(shake, { toValue: 0, duration: 50, useNativeDriver: true }),
    ]).start();
  }

  function handleComplete(otp: string) {
    if (otp !== SIM_OTP) {
      triggerShake();
      setResetTick((t) => t + 1);
      setError('Incorrect code, try again.');
      return;
    }
    Keyboard.dismiss();
    router.replace({
      pathname: '/cardload/processing',
      params: { last4, amount, currency },
    });
  }

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <KeyboardAvoidingView
          style={{ flex: 1 }}
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        >
          <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
            <YStack flex={1}>
              <GradientHeader paddingBottom={22}>
                <HeaderBack title="Verify payment" />
                <StepIndicator step={2} caption="Step 2 of 3 · Confirm it's you" />
              </GradientHeader>

              <ScrollView
                contentContainerStyle={{ flexGrow: 1, padding: 22, gap: 16 }}
                keyboardShouldPersistTaps="handled"
                showsVerticalScrollIndicator={false}
              >
                <YStack gap="$2" marginTop="$2">
                  <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={22} color={colors.text}>
                    Enter the code from your bank
                  </Text>
                  <Text fontFamily="PlusJakartaSans-Medium" fontSize={13.5} color={colors.textMuted}>
                    We sent a 6-digit code to the phone linked to card •••• {last4}.
                  </Text>
                </YStack>
                <Animated.View style={{ transform: [{ translateX: shake }] }}>
                  <OtpInput onComplete={handleComplete} resetSignal={resetTick} />
                </Animated.View>
                {error ? (
                  <Text
                    fontFamily="PlusJakartaSans-Bold"
                    color={colors.danger}
                    fontSize={13}
                    textAlign="center"
                  >
                    {error}
                  </Text>
                ) : null}
                <Text
                  fontFamily="PlusJakartaSans-Medium"
                  color={colors.textMuted}
                  fontSize={12}
                  textAlign="center"
                >
                  Demo OTP: {SIM_OTP}
                </Text>
                <XStack justifyContent="center">
                  <Button
                    unstyled
                    disabled={resendIn > 0}
                    onPress={() => {
                      setResendIn(RESEND_SECONDS);
                      setError(null);
                    }}
                    accessibilityLabel="Resend code"
                  >
                    <Text
                      fontFamily="PlusJakartaSans-SemiBold"
                      fontSize={14}
                      color={resendIn > 0 ? colors.textMuted : colors.navy}
                    >
                      {resendIn > 0 ? `Resend code in ${resendIn}s` : 'Resend code'}
                    </Text>
                  </Button>
                </XStack>
              </ScrollView>
            </YStack>
          </TouchableWithoutFeedback>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
