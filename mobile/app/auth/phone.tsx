/**
 * /auth/phone — phone-entry screen (Sasai Pay redesign).
 *
 * Top: navy gradient hero with the Sasai Pay wordmark.
 * Body: "Welcome back" heading + phone input + Sign in CTA.
 *
 * On Continue:
 *   1. Resolve tenant_id from the in-memory bootstrap call.
 *   2. /auth/start → branch to /auth/pin (returning) or /auth/otp (new).
 *   3. Cache the phone so downstream screens can recover it.
 */
import { useState } from 'react';
import {
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  TouchableWithoutFeedback,
} from 'react-native';
import { useRouter } from 'expo-router';
import { Text, View, XStack, YStack } from 'tamagui';
import { SafeAreaView } from 'react-native-safe-area-context';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { SasaiPayLogo } from '@/components/brand/SasaiPayLogo';
import { PhoneInput } from '@/components/forms/PhoneInput';
import { ClayButton } from '@/components/clay';
import { authStart, otpSend } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/errors';
import { getTenantId } from '@/lib/bootstrap';
import { setLastPhone } from '@/lib/storage';
import { useColors } from '@/lib/colors';

/** Phone entry — entry point of the auth flow. */
export default function PhoneScreen() {
  const colors = useColors();
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
      await otpSend(tenantId, phone);
      router.push({ pathname: '/auth/otp', params: { phone } });
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : 'Something went wrong. Try again.',
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.screenBg }} edges={['bottom']}>
      <KeyboardAvoidingView
        style={{ flex: 1, backgroundColor: colors.screenBg }}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
          <ScrollView
            contentContainerStyle={{ flexGrow: 1 }}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
            bounces={false}
          >
            <GradientHeader paddingBottom={56}>
              <View paddingTop={48}>
                <SasaiPayLogo width={130} />
              </View>
            </GradientHeader>

            <YStack padding={26} gap="$4" flex={1}>
              <YStack gap={4}>
                <Text
                  fontFamily="PlusJakartaSans-ExtraBold"
                  fontSize={25}
                  color={colors.text}
                  letterSpacing={-0.5}
                >
                  Welcome back
                </Text>
                <Text
                  fontFamily="PlusJakartaSans-Regular"
                  fontSize={14}
                  color={colors.textMuted}
                >
                  Sign in to continue to your wallet
                </Text>
              </YStack>

              <View marginTop={18}>
                <PhoneInput onChange={setPhone} />
              </View>

              {error ? (
                <Text
                  fontFamily="PlusJakartaSans-Medium"
                  color={colors.danger}
                  fontSize={13}
                >
                  {error}
                </Text>
              ) : null}

              <View flex={1} minHeight={20} />

              <ClayButton
                onPress={onContinue}
                disabled={!canContinue}
                loading={loading}
                accessibilityLabel="Continue"
              >
                Continue
              </ClayButton>

              <XStack justifyContent="center" marginTop={6}>
                <Text
                  fontFamily="PlusJakartaSans-Regular"
                  fontSize={13}
                  color={colors.textMuted}
                >
                  New to Sasai?{' '}
                </Text>
                <Text
                  fontFamily="PlusJakartaSans-Bold"
                  fontSize={13}
                  color={colors.navy}
                >
                  Create account
                </Text>
              </XStack>
            </YStack>
          </ScrollView>
        </TouchableWithoutFeedback>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
