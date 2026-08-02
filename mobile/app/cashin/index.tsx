/**
 * /cashin — pick the customer whose wallet the agent will fund.
 *
 * Step 1 of the cash-in flow (mirrors /cashout/index). Gradient header with a
 * step indicator, a focused phone input labelled as the CUSTOMER number, and a
 * Continue button that carries the customer phone + active currency forward to
 * the amount screen. The active `currency` comes in via useLocalSearchParams
 * (default "ZAR" when absent) and is threaded through every subsequent screen +
 * the cash-in request; it selects which agent e-float wallet funds the deposit.
 *
 * We do NOT probe the identifier here — whether the phone resolves to a real
 * customer is decided by the backend on submit (404 unknown customer / 422
 * self cash-in), which the amount screen surfaces inline.
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
import { Text, View, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { StepIndicator } from '@/components/brand/StepIndicator';
import { PhoneInput } from '@/components/forms/PhoneInput';
import { ClayButton, ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';

/** Customer picker screen — step 1 of cash-in. */
export default function CashInCustomerScreen() {
  const router = useRouter();
  const colors = useColors();
  const params = useLocalSearchParams<{ currency?: string }>();
  const currency = typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';

  const [phone, setPhone] = useState('');

  const canContinue = phone.replace(/\D/g, '').length >= 9;

  /** Carry the customer phone + currency forward to the amount screen. */
  function goToAmount() {
    if (!canContinue) return;
    router.push({ pathname: '/cashin/amount', params: { phone, currency } });
  }

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
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
                <HeaderBack title="Cash in" />
                <StepIndicator step={1} caption="Step 1 of 3 · Choose the customer to fund" />
              </GradientHeader>

              <YStack padding={22} paddingTop={20} gap={18}>
                {/* What this screen is, in one line — cash-in is agent-funded. */}
                <ClaySurface
                  depth="soft"
                  radius={16}
                  flexDirection="row"
                  alignItems="flex-start"
                  gap={11}
                  padding={14}
                >
                  <Ionicons name="enter-outline" size={20} color={colors.navy} />
                  <YStack flex={1}>
                    <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color={colors.text}>
                      Fund a customer&apos;s wallet
                    </Text>
                    <Text
                      fontFamily="PlusJakartaSans-Medium"
                      fontSize={12}
                      color={colors.textMuted}
                      marginTop={3}
                      lineHeight={18}
                    >
                      Enter the customer&apos;s mobile number. You take their cash and top up
                      their wallet from your e-float, earning a commission.
                    </Text>
                  </YStack>
                </ClaySurface>

                <YStack gap={7}>
                  <PhoneInput onChange={setPhone} variant="focused" />
                  <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color={colors.textMuted}>
                    This must be a registered Sasai customer.
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
