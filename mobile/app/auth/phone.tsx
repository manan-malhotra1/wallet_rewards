/**
 * /auth/phone — country code + phone number entry.
 *
 * On Continue:
 *   1. Resolve tenant_id via the bootstrap call (cached in memory)
 *   2. Call /auth/start to see if the phone is registered
 *   3. needs_pin → cache phone, route to /auth/pin
 *      needs_otp → cache phone, fire /otp/send, route to /auth/otp
 *
 * We persist the phone in secure-store on success so /auth/otp + /auth/pin
 * can recover it from a deep link or app restart.
 */
import { useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  TouchableWithoutFeedback,
} from 'react-native';
import { useRouter } from 'expo-router';
import { Button, Text, View, YStack } from 'tamagui';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PhoneInput } from '@/components/forms/PhoneInput';
import { authStart, otpSend } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/errors';
import { getTenantId } from '@/lib/bootstrap';
import { setLastPhone } from '@/lib/storage';

/** Phone entry screen — the entry point of the auth flow. */
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
      // needs_otp — fire /otp/send and forward
      await otpSend(tenantId, phone);
      router.push({ pathname: '/auth/otp', params: { phone } });
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : 'Something went wrong. Try again.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
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
              <View alignItems="flex-start" marginTop="$2">
                <Image
                  source={require('../../assets/sasai-logo.png')}
                  style={{ width: 152, height: 43, resizeMode: 'contain' }}
                  accessibilityLabel="Sasai"
                />
              </View>
              <YStack gap="$2" marginTop="$5">
                <Text fontFamily="Inter-Bold" fontSize={28} color="#0B1726">
                  Welcome to Sasai
                </Text>
                <Text fontFamily="Inter-Regular" fontSize={15} color="#6A7682">
                  Enter your phone number to sign in or create an account.
                </Text>
              </YStack>
              <View marginTop="$2">
                <PhoneInput onChange={setPhone} />
              </View>
              {error ? (
                <Text fontFamily="Inter-Medium" color="#EF4444" fontSize={13}>
                  {error}
                </Text>
              ) : null}
              <View flex={1} minHeight={40} />
              <Button
                size="$5"
                theme="active"
                backgroundColor="#144989"
                color="white"
                disabled={!canContinue}
                opacity={canContinue ? 1 : 0.5}
                onPress={onContinue}
                accessibilityLabel="Continue"
              >
                {loading ? <ActivityIndicator color="#FFFFFF" /> : 'Continue'}
              </Button>
            </YStack>
          </ScrollView>
        </TouchableWithoutFeedback>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
