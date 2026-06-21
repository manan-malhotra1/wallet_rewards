/**
 * /auth/set-pin — two-step PIN creation.
 *
 * Flow:
 *   - step "enter":   user types a 4-digit PIN
 *   - step "confirm": user re-enters; on match call /pin/set then /auth/pin
 *     to obtain a session_token, persist it, and navigate to /home.
 *
 * The registration_token from /otp/verify lives in secure storage and is
 * consumed exactly once. After /pin/set succeeds we clear it. We then
 * immediately authenticate with /auth/pin so the user lands on a session
 * without an extra screen.
 */
import { useState } from 'react';
import { ActivityIndicator } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, YStack } from 'tamagui';

import { PinInput } from '@/components/forms/PinInput';
import { authPin, pinSet } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/errors';
import { getTenantId } from '@/lib/bootstrap';
import {
  clearRegistrationToken,
  getRegistrationToken,
  setSessionToken,
} from '@/lib/storage';

type Step = 'enter' | 'confirm';

/** PIN creation screen. */
export default function SetPinScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ phone?: string }>();
  const phone = typeof params.phone === 'string' ? params.phone : '';

  const [step, setStep] = useState<Step>('enter');
  const [first, setFirst] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function onFirstComplete(pin: string) {
    setFirst(pin);
    setStep('confirm');
    setError(null);
  }

  async function onConfirmComplete(pin: string) {
    if (pin !== first) {
      setError("Codes don't match. Try again.");
      setStep('enter');
      setFirst('');
      setConfirm('');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const regToken = await getRegistrationToken();
      if (!regToken) {
        throw new Error('Registration session expired. Start again.');
      }
      const tenantId = await getTenantId();
      await pinSet(regToken, pin);
      await clearRegistrationToken();
      // Now exchange phone+PIN for a session_token.
      const { session_token } = await authPin(tenantId, phone, pin);
      await setSessionToken(session_token);
      router.replace('/home');
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : 'Could not set PIN. Try again.';
      setError(msg);
      setStep('enter');
      setFirst('');
      setConfirm('');
    } finally {
      setSubmitting(false);
    }
  }

  if (submitting) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
        <YStack flex={1} alignItems="center" justifyContent="center" gap="$3">
          <ActivityIndicator size="large" color="#144989" />
          <Text fontFamily="Inter-Medium" color="$muted">
            Setting up your wallet…
          </Text>
        </YStack>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
      <YStack flex={1} padding="$5" gap="$5">
        <YStack gap="$2" marginTop="$4">
          <Text fontFamily="Inter-Bold" fontSize={26} color="$ink">
            Create your PIN
          </Text>
          <Text fontFamily="Inter-Regular" fontSize={14} color="$muted">
            {step === 'enter'
              ? 'Choose a 4-digit code. You will use this every time you sign in.'
              : 'Enter the same 4 digits again to confirm.'}
          </Text>
        </YStack>
        {step === 'enter' ? (
          <PinInput
            value={first}
            onChange={setFirst}
            onComplete={onFirstComplete}
            label="Enter PIN"
            errored={!!error}
          />
        ) : (
          <PinInput
            value={confirm}
            onChange={setConfirm}
            onComplete={onConfirmComplete}
            label="Confirm PIN"
            errored={!!error}
          />
        )}
        {error ? (
          <Text fontFamily="Inter-Medium" color="$error" fontSize={13} textAlign="center">
            {error}
          </Text>
        ) : null}
      </YStack>
    </SafeAreaView>
  );
}
