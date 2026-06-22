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
  ActivityIndicator,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  TouchableWithoutFeedback,
} from 'react-native';
import { useRouter } from 'expo-router';
import { Text, View, XStack, YStack } from 'tamagui';
import { SafeAreaView } from 'react-native-safe-area-context';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { SasaiPayLogo } from '@/components/brand/SasaiPayLogo';
import { PhoneInput } from '@/components/forms/PhoneInput';
import { authStart, otpSend } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/errors';
import { getTenantId } from '@/lib/bootstrap';
import { setLastPhone } from '@/lib/storage';

/** Phone entry — entry point of the auth flow. */
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
    <SafeAreaView style={{ flex: 1, backgroundColor: '#ffffff' }} edges={['bottom']}>
      <KeyboardAvoidingView
        style={{ flex: 1, backgroundColor: '#ffffff' }}
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
                  color="#0c1b2a"
                  letterSpacing={-0.5}
                >
                  Welcome back
                </Text>
                <Text
                  fontFamily="PlusJakartaSans-Regular"
                  fontSize={14}
                  color="#6a7888"
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
                  color="#c0392b"
                  fontSize={13}
                >
                  {error}
                </Text>
              ) : null}

              <View flex={1} minHeight={20} />

              <Pressable
                onPress={onContinue}
                disabled={!canContinue}
                accessibilityRole="button"
                accessibilityLabel="Continue"
                style={({ pressed }) => ({
                  opacity: !canContinue ? 0.5 : pressed ? 0.85 : 1,
                })}
              >
                <View
                  height={54}
                  borderRadius={14}
                  backgroundColor="#00508F"
                  alignItems="center"
                  justifyContent="center"
                  shadowColor="#00508F"
                  shadowOpacity={0.28}
                  shadowRadius={24}
                  shadowOffset={{ width: 0, height: 10 }}
                >
                  {loading ? (
                    <ActivityIndicator color="#ffffff" />
                  ) : (
                    <Text
                      fontFamily="PlusJakartaSans-Bold"
                      fontSize={16}
                      color="#ffffff"
                    >
                      Continue
                    </Text>
                  )}
                </View>
              </Pressable>

              <XStack justifyContent="center" marginTop={6}>
                <Text
                  fontFamily="PlusJakartaSans-Regular"
                  fontSize={13}
                  color="#6a7888"
                >
                  New to Sasai?{' '}
                </Text>
                <Text
                  fontFamily="PlusJakartaSans-Bold"
                  fontSize={13}
                  color="#00508F"
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
