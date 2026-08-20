/**
 * /airtime/pending — the recharge is reserved and awaiting the provider
 * callback (the simulator's …0002 numbers land here deliberately).
 *
 * Navy header with a clock, the amount, and the recharge reference. "Check
 * status" re-polls GET /airtime/{id} and routes forward when the recharge
 * turned terminal (callback arrived): COMPLETED → success, REVERSED → failed.
 * The funds stay reserved server-side until the callback / reconciliation
 * resolves them, so Done back to home is always safe.
 */
import { useState } from 'react';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { ClayButton, ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { getAirtimeStatus } from '@/lib/api/airtime';
import { formatMoney, maskPhone } from '@/lib/format';

/** Airtime receipt — still pending, awaiting the provider callback. */
export default function AirtimePendingScreen() {
  const router = useRouter();
  const colors = useColors();
  const params = useLocalSearchParams<{
    id?: string;
    msisdn?: string;
    network?: string;
    amount?: string;
    currency?: string;
  }>();
  const id = typeof params.id === 'string' ? params.id : '';
  const msisdn = typeof params.msisdn === 'string' ? params.msisdn : '';
  const network = typeof params.network === 'string' ? params.network : '—';
  const amount = typeof params.amount === 'string' ? params.amount : '0';
  const currency = typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';

  const [checking, setChecking] = useState(false);
  const [stillPending, setStillPending] = useState(false);

  /**
   * Re-read the recharge once. Terminal → route to the matching receipt;
   * still PENDING → show a gentle "still working on it" line instead.
   */
  async function onCheckStatus() {
    if (!id || checking) return;
    setChecking(true);
    setStillPending(false);
    try {
      const result = await getAirtimeStatus(id);
      if (result.status === 'COMPLETED') {
        router.replace({
          pathname: '/airtime/success',
          params: {
            msisdn,
            network,
            amount,
            currency,
            reference:
              result.provider_reference ?? result.transaction_id.slice(0, 8).toUpperCase(),
          },
        });
        return;
      }
      if (result.status === 'REVERSED') {
        router.replace({
          pathname: '/airtime/failed',
          params: {
            msisdn,
            network,
            amount,
            currency,
            reason:
              result.failure_reason || 'The recharge was reversed. No airtime was delivered.',
          },
        });
        return;
      }
      setStillPending(true);
    } catch {
      // A transient poll failure isn't a recharge failure — just note it.
      setStillPending(true);
    } finally {
      setChecking(false);
    }
  }

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          <GradientHeader paddingBottom={38}>
            <YStack alignItems="center" gap={10} paddingTop={6}>
              <View
                width={78}
                height={78}
                borderRadius={39}
                backgroundColor={colors.clayRaised}
                alignItems="center"
                justifyContent="center"
              >
                <Ionicons name="time-outline" size={44} color={colors.warning} />
              </View>
              <Text
                fontFamily="PlusJakartaSans-ExtraBold"
                fontSize={20}
                color={colors.textOnDark}
                marginTop={4}
              >
                Recharge processing
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
              <XStack gap={11} alignItems="flex-start">
                <Ionicons name="information-circle-outline" size={20} color={colors.navy} />
                <Text
                  fontFamily="PlusJakartaSans-Medium"
                  fontSize={12.5}
                  color={colors.text}
                  lineHeight={19}
                  flexShrink={1}
                >
                  The carrier is confirming your top-up. Your money is safely reserved — if the
                  recharge can't be delivered, it comes straight back to your wallet.
                  {'\n\n'}Reference {id.slice(0, 8).toUpperCase()}
                </Text>
              </XStack>
            </ClaySurface>
            {stillPending ? (
              <Text
                fontFamily="PlusJakartaSans-Medium"
                fontSize={12.5}
                color={colors.textMuted}
                textAlign="center"
              >
                Still processing — check again in a moment.
              </Text>
            ) : null}
          </YStack>

          <YStack paddingHorizontal={18} paddingBottom={18} gap={10}>
            <ClayButton
              onPress={onCheckStatus}
              loading={checking}
              accessibilityLabel="Check status"
            >
              Check status
            </ClayButton>
            <ClayButton
              variant="neutral"
              onPress={() => router.replace('/home')}
              accessibilityLabel="Done"
            >
              Done
            </ClayButton>
          </YStack>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
