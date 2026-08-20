/**
 * /cardload/success — card top-up receipt.
 *
 * Green gradient header with a check mark, the loaded amount, and a receipt
 * card (Card / Amount / Reference / Date). The wallet query was invalidated
 * on the processing screen, so /home shows the new balance on return.
 */
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { ClayButton, ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { formatMoney } from '@/lib/format';

/** Format a Date as "DD MMM YYYY · HH:mm". */
function nowFormatted(): string {
  const d = new Date();
  const date = d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  return `${date} · ${time}`;
}

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

/** Card top-up receipt — success. */
export default function CardLoadSuccessScreen() {
  const router = useRouter();
  const colors = useColors();
  const params = useLocalSearchParams<{
    last4?: string;
    amount?: string;
    currency?: string;
    reference?: string;
  }>();
  const last4 = typeof params.last4 === 'string' ? params.last4 : '';
  const amount = typeof params.amount === 'string' ? params.amount : '0';
  const currency = typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';
  const reference = typeof params.reference === 'string' ? params.reference : '—';

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          <GradientHeader variant="success" paddingBottom={38}>
            <YStack alignItems="center" gap={10} paddingTop={6}>
              <View
                width={78}
                height={78}
                borderRadius={39}
                backgroundColor={colors.clayRaised}
                alignItems="center"
                justifyContent="center"
              >
                <Ionicons name="checkmark" size={46} color="#22a06b" />
              </View>
              <Text
                fontFamily="PlusJakartaSans-ExtraBold"
                fontSize={20}
                color={colors.textOnDark}
                marginTop={4}
              >
                Wallet loaded
              </Text>
              <Text
                fontFamily="PlusJakartaSans-ExtraBold"
                fontSize={33}
                color={colors.textOnDark}
                letterSpacing={-0.5}
              >
                {formatMoney(amount, currency)}
              </Text>
              <Text
                fontFamily="PlusJakartaSans-Medium"
                fontSize={12.5}
                color="rgba(255,255,255,0.85)"
              >
                from card •••• {last4}
              </Text>
            </YStack>
          </GradientHeader>

          <YStack flex={1} padding={18} gap={16}>
            <ClaySurface depth="soft" radius={20} paddingHorizontal={16} paddingVertical={4}>
              <ReceiptRow label="Card" value={`•••• •••• •••• ${last4}`} />
              <ReceiptRow label="Amount loaded" value={formatMoney(amount, currency)} />
              <ReceiptRow label="Reference" value={reference} />
              <ReceiptRow label="Date" value={nowFormatted()} last />
            </ClaySurface>
            <Text
              fontFamily="PlusJakartaSans-Medium"
              fontSize={12}
              color={colors.textMuted}
              textAlign="center"
            >
              The money is in your {currency} wallet and ready to use.
            </Text>
          </YStack>

          <View paddingHorizontal={18} paddingBottom={18}>
            <ClayButton onPress={() => router.replace('/home')} accessibilityLabel="Done">
              Done
            </ClayButton>
          </View>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
