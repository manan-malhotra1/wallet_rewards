/**
 * /p2p/amount — pick how much to send.
 *
 * Pulls the user's ZAR account balance from /me/wallet (cached by the home
 * screen's identical query) and blocks Continue when amount > available.
 * The amount is forwarded to /p2p/review as a route param.
 */
import { useState } from 'react';
import {
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  TouchableWithoutFeedback,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { Button, Text, View, YStack } from 'tamagui';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AmountInput } from '@/components/forms/AmountInput';
import { getMyWallet } from '@/lib/api/wallet';
import { qk } from '@/lib/query';
import { formatZAR, maskPhone } from '@/lib/format';

/** Returns the user's ZAR wallet available_balance (numeric) or 0. */
function pickZarAvailable(
  accounts: { account_type: string; currency: string; available_balance: string }[] | undefined,
): number {
  const zar = accounts?.find(
    (a) => a.currency === 'ZAR' && a.account_type === 'financial_wallet',
  );
  return zar ? parseFloat(zar.available_balance) : 0;
}

/** Amount entry — checks available balance before allowing Continue. */
export default function AmountScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ phone: string }>();
  const recipientPhone = typeof params.phone === 'string' ? params.phone : '';
  const [amount, setAmount] = useState('');
  const { data } = useQuery({ queryKey: qk.wallet(), queryFn: getMyWallet });

  const available = pickZarAvailable(data?.accounts);
  const parsed = parseFloat(amount || '0');
  const overdrawn = parsed > available;
  const canContinue = parsed > 0 && !overdrawn;

  function onContinue() {
    router.push({
      pathname: '/p2p/review',
      params: { phone: recipientPhone, amount },
    });
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
            <YStack flex={1} padding="$5" gap="$5">
              <YStack gap="$2" marginTop="$4">
                <Text fontFamily="Inter-Bold" fontSize={26} color="#0B1726">
                  Amount
                </Text>
                <Text fontFamily="Inter-Regular" fontSize={15} color="#6A7682">
                  Sending to {maskPhone(recipientPhone)}
                </Text>
              </YStack>
              <View marginTop="$3">
                <AmountInput value={amount} onChange={setAmount} />
              </View>
              <Text
                fontFamily="Inter-Regular"
                fontSize={13}
                color="#6A7682"
                textAlign="center"
              >
                ZAR wallet · {formatZAR(available)} available
              </Text>
              {overdrawn ? (
                <Text
                  fontFamily="Inter-Medium"
                  color="#EF4444"
                  fontSize={13}
                  textAlign="center"
                >
                  Not enough in your wallet to send {formatZAR(parsed)}.
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
                accessibilityLabel="Continue to review"
              >
                Continue
              </Button>
            </YStack>
          </ScrollView>
        </TouchableWithoutFeedback>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
