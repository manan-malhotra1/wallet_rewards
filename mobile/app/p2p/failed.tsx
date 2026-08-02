/**
 * /p2p/failed — payment-failed receipt (Sasai Pay redesign).
 *
 * Red gradient header with X mark, "Payment failed", amount, and
 * recipient. Reason callout (red-tinted box) explains why and reassures
 * "no money has left your account". Receipt card with line items.
 * Cancel returns to /home; Try again pops back to /p2p/recipient so
 * the user can re-enter the flow cleanly.
 */
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { ClayButton, ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { maskPhone } from '@/lib/format';

/** Single row in the receipt card. */
function ReceiptRow({ label, value, last }: { label: string; value: string; last?: boolean }) {
  const colors = useColors();
  return (
    <XStack
      justifyContent="space-between"
      paddingVertical={12}
      borderBottomWidth={last ? 0 : 1}
      borderBottomColor={colors.hairline}
      style={{ borderStyle: 'dashed' }}
    >
      <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color={colors.textMuted}>
        {label}
      </Text>
      <Text fontFamily="PlusJakartaSans-Bold" fontSize={12.5} color={colors.text}>
        {value}
      </Text>
    </XStack>
  );
}

/** Failed-payment receipt. */
export default function FailedScreen() {
  const router = useRouter();
  const colors = useColors();
  const params = useLocalSearchParams<{ phone: string; amount: string; reason: string }>();
  const phone = typeof params.phone === 'string' ? params.phone : '';
  const amount = typeof params.amount === 'string' ? params.amount : '0';
  const reason =
    typeof params.reason === 'string' && params.reason.length > 0
      ? params.reason
      : 'Payment failed';

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          <GradientHeader variant="failed" paddingBottom={38}>
            <YStack alignItems="center" gap={10} paddingTop={6}>
              <View
                width={78}
                height={78}
                borderRadius={39}
                backgroundColor={colors.clayRaised}
                alignItems="center"
                justifyContent="center"
                shadowColor="#000000"
                shadowOpacity={0.18}
                shadowRadius={30}
                shadowOffset={{ width: 0, height: 12 }}
              >
                <Ionicons name="close" size={46} color={colors.danger} />
              </View>
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={20} color={colors.textOnDark} marginTop={4}>
                Payment failed
              </Text>
              <Text
                fontFamily="PlusJakartaSans-ExtraBold"
                fontSize={33}
                color={colors.textOnDark}
                letterSpacing={-0.5}
              >
                R {parseFloat(amount).toFixed(2)}
              </Text>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={12.5} color="rgba(255,255,255,0.85)">
                to {maskPhone(phone)}
              </Text>
            </YStack>
          </GradientHeader>

          {/* Reason callout */}
          <XStack
            marginHorizontal={18}
            marginTop={18}
            backgroundColor="#fdf0ee"
            borderColor="#f6d5cf"
            borderWidth={1}
            borderRadius={16}
            padding={14}
            gap={11}
            alignItems="flex-start"
          >
            <Ionicons name="warning" size={20} color={colors.danger} />
            <YStack flex={1}>
              <Text fontFamily="PlusJakartaSans-Bold" fontSize={13} color="#a52e22">
                {reason}
              </Text>
              <Text
                fontFamily="PlusJakartaSans-Medium"
                fontSize={12}
                color="#8a5a54"
                marginTop={3}
                lineHeight={18}
              >
                Your transfer could not be completed. No money has left your account.
              </Text>
            </YStack>
          </XStack>

          {/* Receipt-style details for support reference. */}
          <ClaySurface
            depth="soft"
            radius={18}
            marginHorizontal={18}
            marginTop={14}
            paddingHorizontal={16}
            paddingVertical={6}
          >
            <ReceiptRow label="Recipient" value={maskPhone(phone)} />
            <ReceiptRow label="Amount" value={`R ${parseFloat(amount).toFixed(2)}`} />
            <ReceiptRow label="Status" value="Failed" last />
          </ClaySurface>

          <View flex={1} />

          <XStack gap={12} padding={18}>
            <View flex={1}>
              <ClayButton
                variant="neutral"
                onPress={() => router.replace('/home')}
                height={50}
                accessibilityLabel="Cancel"
              >
                <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color={colors.navy}>
                  Cancel
                </Text>
              </ClayButton>
            </View>
            <View flex={1}>
              <ClayButton
                onPress={() => router.replace('/p2p/recipient')}
                height={50}
                accessibilityLabel="Try again"
              >
                <XStack alignItems="center" gap={7}>
                  <Ionicons name="refresh" size={17} color={colors.textOnDark} />
                  <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color={colors.textOnDark}>
                    Try again
                  </Text>
                </XStack>
              </ClayButton>
            </View>
          </XStack>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
