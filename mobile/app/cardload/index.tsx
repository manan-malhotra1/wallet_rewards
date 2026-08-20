/**
 * /cardload — step 1 of the simulated card top-up: card details + amount.
 *
 * SIMULATOR: no card rails exist. Any 16-digit card number is accepted,
 * along with a future MM/YY expiry and a 3-digit CVV. The amount is what
 * actually gets credited (via the partner fund API on the processing
 * screen) — the card fields are theatre for the load-test scenario.
 */
import { useState } from 'react';
import { Keyboard, KeyboardAvoidingView, Platform, ScrollView, TextInput, TouchableWithoutFeedback } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { StepIndicator } from '@/components/brand/StepIndicator';
import { ClayButton, ClayInset, ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { currencySymbol, formatMoney } from '@/lib/format';

/** Keep digits only, capped at `max` characters. */
function digitsOnly(s: string, max: number): string {
  return s.replace(/\D/g, '').slice(0, max);
}

/** "1234567890123456" → "1234 5678 9012 3456" for display. */
function formatPan(digits: string): string {
  return digits.replace(/(.{4})/g, '$1 ').trim();
}

/** "1226" → "12/26" for display. */
function formatExpiry(digits: string): string {
  if (digits.length <= 2) return digits;
  return `${digits.slice(0, 2)}/${digits.slice(2)}`;
}

/** MM/YY sanity: real month, not in the past (2-digit year = 20YY). */
function expiryValid(digits: string): boolean {
  if (digits.length !== 4) return false;
  const month = parseInt(digits.slice(0, 2), 10);
  const year = 2000 + parseInt(digits.slice(2), 10);
  if (month < 1 || month > 12) return false;
  const now = new Date();
  return year > now.getFullYear() || (year === now.getFullYear() && month >= now.getMonth() + 1);
}

/** Card + amount entry — step 1 of 3. */
export default function CardLoadScreen() {
  const router = useRouter();
  const colors = useColors();
  const params = useLocalSearchParams<{ currency?: string }>();
  const currency =
    typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';

  const [pan, setPan] = useState('');
  const [expiry, setExpiry] = useState('');
  const [cvv, setCvv] = useState('');
  const [amount, setAmount] = useState('');

  const parsed = parseFloat(amount || '0');
  const panOk = pan.length === 16;
  const expiryOk = expiryValid(expiry);
  const cvvOk = cvv.length === 3;
  const amountOk = parsed > 0;
  const canContinue = panOk && expiryOk && cvvOk && amountOk;

  function onAmountChange(next: string) {
    // Digits + at most one dot with 2 decimals — same policy as the keypads.
    const clean = next.replace(/[^\d.]/g, '');
    const [whole = '', ...rest] = clean.split('.');
    const cents = rest.join('').slice(0, 2);
    setAmount(rest.length > 0 ? `${whole.slice(0, 7)}.${cents}` : whole.slice(0, 7));
  }

  function onContinue() {
    if (!canContinue) return;
    router.push({
      pathname: '/cardload/otp',
      params: { last4: pan.slice(-4), amount: parsed.toFixed(2), currency },
    });
  }

  const inputStyle = {
    fontFamily: 'PlusJakartaSans-Bold',
    fontSize: 16,
    color: colors.text,
    paddingVertical: 14,
    paddingHorizontal: 16,
  } as const;

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <KeyboardAvoidingView
          style={{ flex: 1 }}
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        >
          <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
            <YStack flex={1}>
              <GradientHeader paddingBottom={22}>
                <HeaderBack title="Load wallet" />
                <StepIndicator step={1} caption="Step 1 of 3 · Card details" />
              </GradientHeader>

              <ScrollView
                contentContainerStyle={{ padding: 18, gap: 14 }}
                keyboardShouldPersistTaps="handled"
                showsVerticalScrollIndicator={false}
              >
                {/* Card panel. */}
                <ClaySurface depth="soft" radius={20} padding={16} gap={12}>
                  <XStack alignItems="center" gap={8}>
                    <Ionicons name="card" size={18} color={colors.navy} />
                    <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color={colors.text}>
                      Pay with card
                    </Text>
                  </XStack>

                  <YStack gap={6}>
                    <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11.5} color={colors.textMuted}>
                      Card number
                    </Text>
                    <ClayInset radius={14}>
                      <TextInput
                        value={formatPan(pan)}
                        onChangeText={(t) => setPan(digitsOnly(t, 16))}
                        keyboardType="number-pad"
                        placeholder="1234 5678 9012 3456"
                        placeholderTextColor={colors.textFaint}
                        maxLength={19}
                        style={inputStyle}
                        accessibilityLabel="Card number"
                      />
                    </ClayInset>
                  </YStack>

                  <XStack gap={12}>
                    <YStack gap={6} flex={1}>
                      <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11.5} color={colors.textMuted}>
                        Expiry
                      </Text>
                      <ClayInset radius={14}>
                        <TextInput
                          value={formatExpiry(expiry)}
                          onChangeText={(t) => setExpiry(digitsOnly(t, 4))}
                          keyboardType="number-pad"
                          placeholder="MM/YY"
                          placeholderTextColor={colors.textFaint}
                          maxLength={5}
                          style={inputStyle}
                          accessibilityLabel="Card expiry"
                        />
                      </ClayInset>
                    </YStack>
                    <YStack gap={6} flex={1}>
                      <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11.5} color={colors.textMuted}>
                        CVV
                      </Text>
                      <ClayInset radius={14}>
                        <TextInput
                          value={cvv}
                          onChangeText={(t) => setCvv(digitsOnly(t, 3))}
                          keyboardType="number-pad"
                          placeholder="•••"
                          placeholderTextColor={colors.textFaint}
                          maxLength={3}
                          secureTextEntry
                          style={inputStyle}
                          accessibilityLabel="Card CVV"
                        />
                      </ClayInset>
                    </YStack>
                  </XStack>
                  {expiry.length === 4 && !expiryOk ? (
                    <Text fontFamily="PlusJakartaSans-Bold" fontSize={12} color={colors.danger}>
                      That expiry date has passed.
                    </Text>
                  ) : null}
                </ClaySurface>

                {/* Amount panel. */}
                <ClaySurface depth="soft" radius={20} padding={16} gap={12}>
                  <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color={colors.text}>
                    Amount to load
                  </Text>
                  <ClayInset radius={14}>
                    <XStack alignItems="center" paddingLeft={16}>
                      <Text fontFamily="PlusJakartaSans-Bold" fontSize={16} color={colors.textFaint}>
                        {currencySymbol(currency).trim()}
                      </Text>
                      <TextInput
                        value={amount}
                        onChangeText={onAmountChange}
                        keyboardType="decimal-pad"
                        placeholder="0.00"
                        placeholderTextColor={colors.textFaint}
                        style={[inputStyle, { flex: 1, paddingLeft: 8 }]}
                        accessibilityLabel="Amount to load"
                      />
                    </XStack>
                  </ClayInset>
                  <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color={colors.textMuted}>
                    Loads directly into your {currency} wallet after verification.
                  </Text>
                </ClaySurface>
              </ScrollView>

              <View paddingHorizontal={18} paddingBottom={18} paddingTop={4}>
                <ClayButton
                  onPress={onContinue}
                  disabled={!canContinue}
                  accessibilityLabel="Continue to verification"
                >
                  {amountOk ? `Load ${formatMoney(parsed, currency)}` : 'Continue'}
                </ClayButton>
              </View>
            </YStack>
          </TouchableWithoutFeedback>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
