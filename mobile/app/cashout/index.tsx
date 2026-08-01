/**
 * /cashout — pick the agent (cash-out point) to withdraw from.
 *
 * Step 1 of the cash-out flow (mirrors /p2p/recipient). Gradient header with
 * a step indicator, a focused phone input labelled as the agent / cash-out
 * point, and a Continue button that carries the agent phone + active currency
 * forward to the amount screen. The active `currency` comes in via
 * useLocalSearchParams (default "ZAR" when absent) and is threaded through
 * every subsequent screen + the cash-out request.
 *
 * Unlike P2P we do NOT probe the identifier here — whether the phone resolves
 * to a real AGENT is decided by the backend on submit (404 unknown agent /
 * 422 recipient not an agent), which the amount screen surfaces inline.
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
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { StepIndicator } from '@/components/brand/StepIndicator';
import { PhoneInput } from '@/components/forms/PhoneInput';
import { ClayButton, ClaySurface } from '@/components/clay';

/** Agent picker screen — step 1 of cash-out. */
export default function CashOutAgentScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ currency?: string }>();
  const currency = typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';

  const [phone, setPhone] = useState('');

  const canContinue = phone.replace(/\D/g, '').length >= 9;

  /** Carry the agent phone + currency forward to the amount screen. */
  function goToAmount() {
    if (!canContinue) return;
    router.push({ pathname: '/cashout/amount', params: { phone, currency } });
  }

  return (
    <View flex={1} backgroundColor="#ccd8e8">
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <KeyboardAvoidingView
          style={{ flex: 1 }}
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        >
          <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
            <ScrollView
              contentContainerStyle={{ flexGrow: 1, paddingBottom: 24 }}
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator={false}
              bounces={false}
            >
              <GradientHeader paddingBottom={24}>
                <HeaderBack title="Cash out" />
                <StepIndicator step={1} caption="Step 1 of 3 · Choose your cash-out agent" />
              </GradientHeader>

              <YStack padding={22} paddingTop={20} gap={18}>
                {/* What this screen is, in one line — cash-out is agent-mediated. */}
                <ClaySurface
                  depth="soft"
                  radius={16}
                  flexDirection="row"
                  alignItems="flex-start"
                  gap={11}
                  padding={14}
                >
                  <Ionicons name="cash-outline" size={20} color="#00508F" />
                  <YStack flex={1}>
                    <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color="#0c1b2a">
                      Withdraw with an agent
                    </Text>
                    <Text
                      fontFamily="PlusJakartaSans-Medium"
                      fontSize={12}
                      color="#5a6b7b"
                      marginTop={3}
                      lineHeight={18}
                    >
                      Enter your agent&apos;s mobile number. You send the amount from your
                      wallet and the agent hands you the cash.
                    </Text>
                  </YStack>
                </ClaySurface>

                <YStack gap={7}>
                  <PhoneInput onChange={setPhone} variant="focused" />
                  <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color="#8a98a6">
                    This must be a registered Sasai cash-out agent.
                  </Text>
                </YStack>

                <ClayButton
                  onPress={goToAmount}
                  disabled={!canContinue}
                  height={50}
                  accessibilityLabel="Continue"
                >
                  Continue
                </ClayButton>
              </YStack>
            </ScrollView>
          </TouchableWithoutFeedback>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
