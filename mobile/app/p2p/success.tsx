/**
 * /p2p/success — payment receipt (Sasai Pay redesign).
 *
 * Green gradient header w/ check mark, "Payment successful", amount,
 * and recipient. White receipt card with dashed dividers shows the
 * line-item details (Recipient / Mobile / Amount / Fee / Reference /
 * Date). If `earned > 0`, a "You earned X reward points" line sits
 * above the action row. Done routes back to /home with the wallet
 * query already invalidated by the PIN screen.
 */
import { Pressable } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { maskPhone } from '@/lib/format';

/** Format a Date as "DD MMM YYYY · HH:mm". */
function nowFormatted(): string {
  const d = new Date();
  const date = d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  return `${date} · ${time}`;
}

/** Single Recipient/Amount/etc. row in the receipt card. */
function ReceiptRow({ label, value, last }: { label: string; value: string; last?: boolean }) {
  return (
    <XStack
      justifyContent="space-between"
      paddingVertical={12}
      borderBottomWidth={last ? 0 : 1}
      borderBottomColor="#e7edf2"
      // dashed via opacity + width; React Native's `borderStyle: 'dashed'` is
      // unreliable across platforms, so a soft line is used instead.
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

/** Payment receipt — success. */
export default function SuccessScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{
    phone: string;
    amount: string;
    earned: string;
    reference: string;
  }>();
  const phone = typeof params.phone === 'string' ? params.phone : '';
  const amount = typeof params.amount === 'string' ? params.amount : '0';
  const earned = parseInt(typeof params.earned === 'string' ? params.earned : '0', 10) || 0;
  const reference = typeof params.reference === 'string' ? params.reference : '—';

  return (
    <View flex={1} backgroundColor="#ffffff">
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
                <Text fontSize={40} color="#0a8a5f">
                  ✓
                </Text>
              </View>
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={20} color="#ffffff" marginTop={4}>
                Payment successful
              </Text>
              <Text
                fontFamily="PlusJakartaSans-ExtraBold"
                fontSize={33}
                color="#ffffff"
                letterSpacing={-0.5}
              >
                R {parseFloat(amount).toFixed(2)}
              </Text>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={12.5} color="rgba(255,255,255,0.85)">
                to {maskPhone(phone)}
              </Text>
            </YStack>
          </GradientHeader>

          {/* Receipt card */}
          <View
            marginHorizontal={18}
            marginTop={18}
            backgroundColor="#ffffff"
            borderColor="#eef2f6"
            borderWidth={1}
            borderRadius={18}
            paddingHorizontal={16}
            paddingVertical={6}
            shadowColor="#0c1b2a"
            shadowOpacity={0.05}
            shadowRadius={16}
            shadowOffset={{ width: 0, height: 6 }}
          >
            <ReceiptRow label="Recipient" value={maskPhone(phone)} />
            <ReceiptRow label="Mobile" value={maskPhone(phone)} />
            <ReceiptRow label="Amount" value={`R ${parseFloat(amount).toFixed(2)}`} />
            <ReceiptRow label="Fee" value="R 0.00" />
            <ReceiptRow label="Reference" value={`SASAI-${reference}`} />
            <ReceiptRow label="Date" value={nowFormatted()} last />
          </View>

          {earned > 0 ? (
            <XStack
              alignItems="center"
              justifyContent="center"
              gap={7}
              marginTop={14}
            >
              <Text fontSize={14}>⭐</Text>
              <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#0a8a5f">
                You earned {earned} reward points
              </Text>
            </XStack>
          ) : null}

          <View flex={1} />

          <XStack gap={12} padding={18}>
            <Pressable
              onPress={() => {}}
              accessibilityLabel="Share receipt"
              style={({ pressed }) => ({ flex: 1, opacity: pressed ? 0.7 : 1 })}
            >
              <View
                height={50}
                borderRadius={14}
                borderWidth={1.5}
                borderColor="#e2e8ef"
                alignItems="center"
                justifyContent="center"
                flexDirection="row"
                gap={7}
              >
                <Text fontSize={15}>⤓</Text>
                <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#0c1b2a">
                  Share
                </Text>
              </View>
            </Pressable>
            <Pressable
              onPress={() => router.replace('/home')}
              accessibilityLabel="Done"
              style={({ pressed }) => ({ flex: 1, opacity: pressed ? 0.85 : 1 })}
            >
              <View
                height={50}
                borderRadius={14}
                backgroundColor="#00508F"
                alignItems="center"
                justifyContent="center"
              >
                <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#ffffff">
                  Done
                </Text>
              </View>
            </Pressable>
          </XStack>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
