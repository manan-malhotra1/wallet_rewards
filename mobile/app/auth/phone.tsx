/**
 * /auth/phone — phone-entry screen (Sasai Pay redesign).
 *
 * Top: navy gradient hero with the Sasai Pay wordmark.
 * Body: "Welcome back" heading + phone input + Sign in CTA.
 *
 * Self-registration is phone-first: /otp/send auto-registers an unknown phone,
 * so "Create account" is the SAME flow with one addition — an optional referral
 * code. Tapping "Create account" reveals a "Referral code (optional)" field and
 * the existing Continue handler threads the code to /otp/send.
 *
 * On Continue:
 *   1. Resolve tenant_id from the in-memory bootstrap call.
 *   2. /auth/start → branch to /auth/pin (returning) or /auth/otp (new).
 *   3. For a new phone, /otp/send carries the referral code (if entered).
 *   4. Cache the phone so downstream screens can recover it.
 */
import { useState } from 'react';
import {
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
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
  // Referral capture is opt-in — revealed by tapping "Create account".
  const [showReferral, setShowReferral] = useState(false);
  const [referralCode, setReferralCode] = useState('');
  const [referralError, setReferralError] = useState<string | null>(null);

  const canContinue = phone.replace(/\D/g, '').length >= 9 && !loading;

  /** Reveal the optional referral field (self-registration entry point). */
  function onCreateAccount() {
    setShowReferral(true);
    setError(null);
  }

  async function onContinue() {
    setLoading(true);
    setError(null);
    setReferralError(null);
    try {
      const tenantId = await getTenantId();
      const { status } = await authStart(tenantId, phone);
      await setLastPhone(phone);
      if (status === 'needs_pin') {
        router.push({ pathname: '/auth/pin', params: { phone } });
        return;
      }
      // New phone → auto-register via OTP, carrying the referral code if entered.
      await otpSend(tenantId, phone, referralCode);
      router.push({ pathname: '/auth/otp', params: { phone } });
    } catch (e) {
      // An invalid referral code is recoverable inline — the code is optional,
      // so surface it on the field and let the user fix or clear it and retry.
      if (e instanceof ApiError && e.errorCode === 'invalid_referral_code') {
        setShowReferral(true);
        setReferralError("That referral code isn't valid");
      } else {
        setError(
          e instanceof ApiError
            ? e.message
            : e instanceof Error
              ? e.message
              : 'Something went wrong. Try again.',
        );
      }
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
                  {showReferral ? 'Create your account' : 'Welcome back'}
                </Text>
                <Text
                  fontFamily="PlusJakartaSans-Regular"
                  fontSize={14}
                  color={colors.textMuted}
                >
                  {showReferral
                    ? 'Enter your number to get started'
                    : 'Sign in to continue to your wallet'}
                </Text>
              </YStack>

              <View marginTop={18}>
                <PhoneInput onChange={setPhone} />
              </View>

              {showReferral ? (
                <YStack gap="$2" marginTop={4}>
                  <Text
                    fontFamily="PlusJakartaSans-SemiBold"
                    fontSize={12}
                    color={colors.textMuted}
                  >
                    Referral code (optional)
                  </Text>
                  <XStack
                    alignItems="center"
                    borderWidth={1.5}
                    borderColor={referralError ? colors.danger : colors.hairline}
                    borderRadius={16}
                    paddingHorizontal={14}
                    height={54}
                    backgroundColor={colors.clayInset}
                  >
                    <TextInput
                      value={referralCode}
                      onChangeText={(next) => {
                        // Codes are case-insensitive on the backend; upper-case
                        // for a consistent, legible display as the user types.
                        setReferralCode(next.toUpperCase());
                        if (referralError) setReferralError(null);
                      }}
                      autoCapitalize="characters"
                      autoCorrect={false}
                      placeholder="e.g. YDEFA4BC"
                      placeholderTextColor={colors.textFaint}
                      style={{
                        flex: 1,
                        paddingVertical: 8,
                        fontSize: 15,
                        letterSpacing: 1,
                        fontFamily: 'PlusJakartaSans-Bold',
                        color: colors.text,
                      }}
                      accessibilityLabel="Referral code"
                      maxLength={16}
                    />
                  </XStack>
                  {referralError ? (
                    <Text
                      fontFamily="PlusJakartaSans-Medium"
                      color={colors.danger}
                      fontSize={13}
                    >
                      {referralError}
                    </Text>
                  ) : null}
                </YStack>
              ) : null}

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

              {!showReferral ? (
                <XStack justifyContent="center" marginTop={6}>
                  <Text
                    fontFamily="PlusJakartaSans-Regular"
                    fontSize={13}
                    color={colors.textMuted}
                  >
                    New to Sasai?{' '}
                  </Text>
                  <Pressable
                    onPress={onCreateAccount}
                    accessibilityRole="button"
                    accessibilityLabel="Create account"
                  >
                    <Text
                      fontFamily="PlusJakartaSans-Bold"
                      fontSize={13}
                      color={colors.navy}
                    >
                      Create account
                    </Text>
                  </Pressable>
                </XStack>
              ) : null}
            </YStack>
          </ScrollView>
        </TouchableWithoutFeedback>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
