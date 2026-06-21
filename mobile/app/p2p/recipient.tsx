/**
 * /p2p/recipient — pick who you're sending to (by phone number).
 *
 * Re-uses `/auth/start` as a lookup probe: a phone that returns `needs_otp`
 * isn't a registered Sasai user yet, so we reject with a friendly inline
 * error rather than letting the P2P call fail server-side. This shaves a
 * round-trip and gives a tighter error message.
 */
import { useState } from 'react';
import {
  ActivityIndicator,
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
import { authStart } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/errors';
import { getTenantId } from '@/lib/bootstrap';

/** Send-money recipient picker — phone number entry. */
export default function RecipientScreen() {
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
      if (status === 'needs_otp') {
        // Not a registered user yet — short-circuit before /payments/p2p.
        setError("That number isn't on Sasai yet.");
        return;
      }
      router.push({ pathname: '/p2p/amount', params: { phone } });
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : 'Lookup failed. Try again.';
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
              <YStack gap="$2" marginTop="$4">
                <Text fontFamily="Inter-Bold" fontSize={26} color="#0B1726">
                  Send money
                </Text>
                <Text fontFamily="Inter-Regular" fontSize={15} color="#6A7682">
                  Who are you sending to?
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
                accessibilityLabel="Continue to amount"
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
