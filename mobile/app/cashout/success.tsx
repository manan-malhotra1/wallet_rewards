/**
 * /cashout/success — cash-out receipt.
 *
 * Green gradient header with a check mark, "Cash-out successful", the amount,
 * and "paid to agent". A receipt card lists Agent / Amount / Fee / Reference /
 * Date. All money renders via formatMoney(amount, currency). Done routes back
 * to /home (the wallet query was invalidated before we got here).
 */
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { ClayButton, ClaySurface } from '@/components/clay';
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
  return (
    <XStack
      justifyContent="space-between"
      paddingVertical={12}
      borderBottomWidth={last ? 0 : 1}
      borderBottomColor="#e7edf2"
      style={{ borderStyle: 'dashed' }}
    >
      <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#8a98a6">
        {label}
      </Text>
      <Text fontFamily="PlusJakartaSans-Bold" fontSize={12.5} color="#0c1b2a">
        {value}
      </Text>
    </XStack>
  );
}

/** Cash-out receipt — success. */
export default function CashOutSuccessScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{
    phone?: string;
    amount?: string;
    fee?: string;
    currency?: string;
    reference?: string;
  }>();
  const phone = typeof params.phone === 'string' ? params.phone : '';
  const amount = typeof params.amount === 'string' ? params.amount : '0';
  const fee = typeof params.fee === 'string' ? params.fee : '0';
  const currency = typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';
  const reference = typeof params.reference === 'string' ? params.reference : '—';

  return (
    <View flex={1} backgroundColor="#ccd8e8">
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          <GradientHeader variant="success" paddingBottom={38}>
            <YStack alignItems="center" gap={10} paddingTop={6}>
              <View
                width={78}
                height={78}
                borderRadius={39}
                backgroundColor="#ffffff"
                alignItems="center"
                justifyContent="center"
                shadowColor="#000000"
                shadowOpacity={0.18}
                shadowRadius={30}
                shadowOffset={{ width: 0, height: 12 }}
              >
                <Ionicons name="checkmark" size={44} color="#0a8a5f" />
              </View>
              <Text
                fontFamily="PlusJakartaSans-ExtraBold"
                fontSize={20}
                color="#ffffff"
                marginTop={4}
              >
                Cash-out successful
              </Text>
              <Text
                fontFamily="PlusJakartaSans-ExtraBold"
                fontSize={33}
                color="#ffffff"
                letterSpacing={-0.5}
              >
                {formatMoney(amount, currency)}
              </Text>
              <Text
                fontFamily="PlusJakartaSans-Medium"
                fontSize={12.5}
                color="rgba(255,255,255,0.85)"
              >
                paid to agent {maskPhone(phone)}
              </Text>
            </YStack>
          </GradientHeader>

          {/* Receipt card. */}
          <ClaySurface
            depth="soft"
            radius={18}
            marginHorizontal={18}
            marginTop={18}
            paddingHorizontal={16}
            paddingVertical={6}
          >
            <ReceiptRow label="Agent" value={maskPhone(phone)} />
            <ReceiptRow label="Amount" value={formatMoney(amount, currency)} />
            <ReceiptRow label="Fee" value={formatMoney(fee, currency)} />
            <ReceiptRow label="Reference" value={`SASAI-${reference}`} />
            <ReceiptRow label="Date" value={nowFormatted()} last />
          </ClaySurface>

          {/* Reassurance line — the physical cash is handed over by the agent. */}
          <XStack alignItems="center" justifyContent="center" gap={7} marginTop={14}>
            <Ionicons name="cash-outline" size={15} color="#0a8a5f" />
            <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#0a8a5f">
              Collect your cash from the agent
            </Text>
          </XStack>

          <View flex={1} />

          <XStack gap={12} padding={18}>
            <View flex={1}>
              <ClayButton
                variant="neutral"
                onPress={() => {}}
                height={50}
                accessibilityLabel="Share receipt"
              >
                <XStack alignItems="center" gap={7}>
                  <Ionicons name="share-outline" size={17} color="#00508F" />
                  <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#00508F">
                    Share
                  </Text>
                </XStack>
              </ClayButton>
            </View>
            <View flex={1}>
              <ClayButton onPress={() => router.replace('/home')} height={50} accessibilityLabel="Done">
                Done
              </ClayButton>
            </View>
          </XStack>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
