/**
 * /airtime/success — airtime receipt, mirroring the P2P / cash-in pattern.
 *
 * Green gradient header with a check mark, the amount, and "to <number>". A
 * receipt card lists Number / Network / Amount / Reference / Date. Done routes
 * back to /home (the wallet query was invalidated before navigating here).
 */
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { ClayButton, ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { formatMoney, maskPhone } from '@/lib/format';

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

/** Airtime receipt — success. */
export default function AirtimeSuccessScreen() {
  const router = useRouter();
  const colors = useColors();
  const params = useLocalSearchParams<{
    msisdn?: string;
    network?: string;
    amount?: string;
    currency?: string;
    reference?: string;
  }>();
  const msisdn = typeof params.msisdn === 'string' ? params.msisdn : '';
  const network = typeof params.network === 'string' ? params.network : '—';
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
                Airtime sent
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
                to {maskPhone(msisdn)} on {network}
              </Text>
            </YStack>
          </GradientHeader>

          <YStack flex={1} padding={18} gap={16}>
            <ClaySurface depth="soft" radius={20} paddingHorizontal={16} paddingVertical={4}>
              <ReceiptRow label="Number" value={maskPhone(msisdn)} />
              <ReceiptRow label="Network" value={network} />
              <ReceiptRow label="Amount" value={formatMoney(amount, currency)} />
              <ReceiptRow label="Reference" value={reference} />
              <ReceiptRow label="Date" value={nowFormatted()} last />
            </ClaySurface>
            <Text
              fontFamily="PlusJakartaSans-Medium"
              fontSize={12}
              color={colors.textMuted}
              textAlign="center"
            >
              The airtime has been delivered to the number.
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
