/**
 * /airtime/failed — the recharge didn't complete (provider failure, reversal,
 * or a pre-ledger rejection). Red gradient header with the attempted amount
 * and a friendly reason; funds — if they were reserved — were refunded
 * server-side. "Try again" returns to the airtime form; "Back to home" bails.
 */
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { ClayButton, ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { formatMoney, maskPhone } from '@/lib/format';

/** Airtime receipt — failed / reversed. */
export default function AirtimeFailedScreen() {
  const router = useRouter();
  const colors = useColors();
  const params = useLocalSearchParams<{
    msisdn?: string;
    network?: string;
    amount?: string;
    currency?: string;
    reason?: string;
  }>();
  const msisdn = typeof params.msisdn === 'string' ? params.msisdn : '';
  const network = typeof params.network === 'string' ? params.network : '—';
  const amount = typeof params.amount === 'string' ? params.amount : '0';
  const currency = typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';
  const reason =
    typeof params.reason === 'string' && params.reason.length > 0
      ? params.reason
      : 'The recharge could not be completed.';

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
              >
                <Ionicons name="close" size={46} color={colors.danger} />
              </View>
              <Text
                fontFamily="PlusJakartaSans-ExtraBold"
                fontSize={20}
                color={colors.textOnDark}
                marginTop={4}
              >
                Recharge failed
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
            <ClaySurface depth="soft" radius={20} padding={16}>
              <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color={colors.text}>
                What happened?
              </Text>
              <Text
                fontFamily="PlusJakartaSans-Medium"
                fontSize={12.5}
                color={colors.textMuted}
                marginTop={6}
                lineHeight={19}
              >
                {reason}
              </Text>
              <Text
                fontFamily="PlusJakartaSans-Medium"
                fontSize={12.5}
                color={colors.textMuted}
                marginTop={6}
              >
                Any reserved funds have been returned to your wallet.
              </Text>
            </ClaySurface>
          </YStack>

          <YStack paddingHorizontal={18} paddingBottom={18} gap={10}>
            <ClayButton
              onPress={() => router.replace('/airtime')}
              accessibilityLabel="Try again"
            >
              Try again
            </ClayButton>
            <ClayButton
              variant="neutral"
              onPress={() => router.replace('/home')}
              accessibilityLabel="Back to home"
            >
              Back to home
            </ClayButton>
          </YStack>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
