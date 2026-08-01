/**
 * /p2p/recipient — pick who you're sending to (Sasai Pay redesign).
 *
 * Step 1 of the send-money flow. Gradient header w/ step indicator,
 * focused phone input, and a "Recent payments" section with both a
 * horizontal avatar row and a tappable list. The list + avatars use
 * static demo data for v0 (we don't have a "recent recipients" backend
 * endpoint yet); tapping any of them deep-links to the amount screen
 * pre-filled.
 *
 * Continue uses /auth/start as a lookup probe — if the phone isn't a
 * Sasai user yet, we reject with a friendly inline error rather than
 * letting /payments/p2p fail server-side.
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

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { StepIndicator } from '@/components/brand/StepIndicator';
import { PhoneInput } from '@/components/forms/PhoneInput';
import { ClayButton, ClaySurface } from '@/components/clay';
import { authStart } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/errors';
import { getTenantId } from '@/lib/bootstrap';

/** Demo recent recipients. Real "recent contacts" surfacing is Phase 2. */
const RECENTS = [
  { initials: 'AL', name: 'Alice',  phone: '+27825550001', bg: '#50C0D0', fg: '#013a6b' },
  { initials: 'BB', name: 'Bob',    phone: '+27825550002', bg: '#eef3fb', fg: '#00508F' },
  { initials: 'TC', name: 'Tariro', phone: '+263786612093', bg: '#fff7e6', fg: '#c98a00' },
  { initials: 'RS', name: 'Rudo',   phone: '+263787715040', bg: '#fdeef0', fg: '#c0455a' },
] as const;

/** Recipient picker screen. */
export default function RecipientScreen() {
  const router = useRouter();
  // Active wallet currency arrives via ?currency= from /home and is carried
  // forward to the amount screen so sendP2P debits the right wallet. Defaults
  // to ZAR if the param is missing so the flow never breaks.
  const params = useLocalSearchParams<{ currency?: string }>();
  const currency = typeof params.currency === 'string' ? params.currency : 'ZAR';
  const [phone, setPhone] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canContinue = phone.replace(/\D/g, '').length >= 9 && !loading;

  async function lookupAndGoToAmount(target: string) {
    setLoading(true);
    setError(null);
    try {
      const tenantId = await getTenantId();
      const { status } = await authStart(tenantId, target);
      if (status === 'needs_otp') {
        setError("That number isn't on Sasai yet.");
        return;
      }
      router.push({ pathname: '/p2p/amount', params: { phone: target, currency } });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Lookup failed. Try again.');
    } finally {
      setLoading(false);
    }
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
                <HeaderBack title="Send money" />
                <StepIndicator step={1} caption="Step 1 of 3 · Who are you paying?" />
              </GradientHeader>

              <YStack padding={22} paddingTop={20} gap={18}>
                <PhoneInput onChange={setPhone} variant="focused" />

                {error ? (
                  <Text fontFamily="PlusJakartaSans-Medium" color="#c0392b" fontSize={13}>
                    {error}
                  </Text>
                ) : null}

                <ClayButton
                  onPress={() => lookupAndGoToAmount(phone)}
                  disabled={!canContinue}
                  loading={loading}
                  height={50}
                  accessibilityLabel="Continue"
                >
                  Continue
                </ClayButton>

                {/* Recent payments — header */}
                <XStack justifyContent="space-between" alignItems="center" marginTop={6}>
                  <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={14} color="#0c1b2a">
                    Recent payments
                  </Text>
                  <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#00508F">
                    View all
                  </Text>
                </XStack>
              </YStack>

              {/* Avatar row */}
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={{ paddingHorizontal: 22, gap: 16 }}
              >
                {RECENTS.map((r) => (
                  <Pressable
                    key={r.phone}
                    onPress={() => lookupAndGoToAmount(r.phone)}
                    accessibilityRole="button"
                    accessibilityLabel={`Send to ${r.name}`}
                    style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}
                  >
                    <YStack alignItems="center" gap={7} width={58}>
                      <View
                        width={52}
                        height={52}
                        borderRadius={26}
                        backgroundColor={r.bg}
                        borderWidth={r.bg === '#50C0D0' ? 2.5 : 0}
                        borderColor="#00508F"
                        alignItems="center"
                        justifyContent="center"
                      >
                        <Text fontFamily="PlusJakartaSans-Bold" fontSize={16} color={r.fg}>
                          {r.initials}
                        </Text>
                      </View>
                      <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11} color="#3a4756">
                        {r.name}
                      </Text>
                    </YStack>
                  </Pressable>
                ))}
              </ScrollView>

              {/* Selectable list */}
              <ClaySurface
                depth="soft"
                radius={18}
                marginHorizontal={18}
                marginTop={14}
                paddingHorizontal={14}
              >
                {RECENTS.map((r, i) => (
                  <Pressable
                    key={r.phone}
                    onPress={() => lookupAndGoToAmount(r.phone)}
                    accessibilityRole="button"
                    style={({ pressed }) => ({ opacity: pressed ? 0.6 : 1 })}
                  >
                    <XStack
                      alignItems="center"
                      gap={12}
                      paddingVertical={12}
                      borderBottomWidth={i === RECENTS.length - 1 ? 0 : 1}
                      borderBottomColor="rgba(1,46,84,0.06)"
                    >
                      <View
                        width={42}
                        height={42}
                        borderRadius={21}
                        backgroundColor={r.bg}
                        alignItems="center"
                        justifyContent="center"
                      >
                        <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color={r.fg}>
                          {r.initials}
                        </Text>
                      </View>
                      <YStack flex={1} gap={1}>
                        <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#0c1b2a">
                          {r.name}
                        </Text>
                        <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color="#8a98a6">
                          {r.phone}
                        </Text>
                      </YStack>
                      <Text fontSize={18} color="#cfd9e3">›</Text>
                    </XStack>
                  </Pressable>
                ))}
              </ClaySurface>
            </ScrollView>
          </TouchableWithoutFeedback>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
