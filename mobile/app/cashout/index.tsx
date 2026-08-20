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
  Pressable,
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
import { useColors } from '@/lib/colors';

/**
 * Quick-pick cash-out agents — the seeded dev-tenant agents, mirroring the
 * P2P recents / airtime quick-pick lists. Tapping one goes straight to the
 * amount screen (the backend still validates the agent on submit).
 */
const AGENTS = [
  { initials: 'SA', name: 'Sipho (Agent)', phone: '+27825558001', bg: '#eaf1fb', fg: '#00508F' },
  { initials: 'SU', name: 'Naledi (Super agent)', phone: '+278610000001', bg: '#fff7e6', fg: '#c98a00' },
  { initials: 'AG', name: 'Kagiso (Agent)', phone: '+278620000006', bg: '#fdeef0', fg: '#c0455a' },
] as const;

/** Agent picker screen — step 1 of cash-out. */
export default function CashOutAgentScreen() {
  const router = useRouter();
  const colors = useColors();
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
                  <Ionicons name="cash-outline" size={20} color={colors.navy} />
                  <YStack flex={1}>
                    <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color={colors.text}>
                      Withdraw with an agent
                    </Text>
                    <Text
                      fontFamily="PlusJakartaSans-Medium"
                      fontSize={12}
                      color={colors.textMuted}
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
                  <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color={colors.textMuted}>
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

                {/* Quick-pick agents — tap goes straight to the amount screen. */}
                <YStack gap={8} marginTop={4}>
                  <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={14} color={colors.text}>
                    Agents near you
                  </Text>
                  <ClaySurface depth="soft" radius={18} paddingHorizontal={14}>
                    {AGENTS.map((a, i) => (
                      <Pressable
                        key={a.phone}
                        onPress={() =>
                          router.push({
                            pathname: '/cashout/amount',
                            params: { phone: a.phone, currency },
                          })
                        }
                        accessibilityRole="button"
                        accessibilityLabel={`Cash out with ${a.name}`}
                        style={({ pressed }) => ({ opacity: pressed ? 0.6 : 1 })}
                      >
                        <XStack
                          alignItems="center"
                          gap={12}
                          paddingVertical={12}
                          borderBottomWidth={i === AGENTS.length - 1 ? 0 : 1}
                          borderBottomColor={colors.hairline}
                        >
                          <View
                            width={42}
                            height={42}
                            borderRadius={21}
                            backgroundColor={a.bg}
                            alignItems="center"
                            justifyContent="center"
                          >
                            <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color={a.fg}>
                              {a.initials}
                            </Text>
                          </View>
                          <YStack flex={1} gap={1}>
                            <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color={colors.text}>
                              {a.name}
                            </Text>
                            <Text
                              fontFamily="PlusJakartaSans-Medium"
                              fontSize={11.5}
                              color={colors.textMuted}
                            >
                              {a.phone}
                            </Text>
                          </YStack>
                          <Text fontSize={18} color={colors.textFaint}>›</Text>
                        </XStack>
                      </Pressable>
                    ))}
                  </ClaySurface>
                </YStack>
              </YStack>
            </ScrollView>
          </TouchableWithoutFeedback>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
