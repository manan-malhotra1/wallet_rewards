/**
 * /cardload/processing — step 3 of the simulated card top-up: the loader.
 *
 * Shows a full-screen "confirming with your bank" spinner while the wallet
 * is ACTUALLY credited via the partner fund API (cash float). A minimum
 * display time keeps the loader readable, Android hardware-back is blocked,
 * and a ref guards the effect so the fund call fires exactly once (the
 * idempotency key would dedupe a double-fire anyway — belt and braces).
 */
import { useEffect, useRef } from 'react';
import { ActivityIndicator, BackHandler } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { useQueryClient } from '@tanstack/react-query';
import {
  cardLoadFailureReason,
  cardSimConfigured,
  loadFromCard,
  newCardLoadIdempotencyKey,
} from '@/lib/api/cardload';
import { formatMoney } from '@/lib/format';
import { qk } from '@/lib/query';
import { getLastPhone } from '@/lib/storage';

/** Keep the loader on screen at least this long — instant flashes read as broken. */
const MIN_SPINNER_MS = 2500;

/** Bank-confirmation loader — step 3 of 3. */
export default function CardLoadProcessingScreen() {
  const router = useRouter();
  const colors = useColors();
  const qc = useQueryClient();
  const params = useLocalSearchParams<{ last4?: string; amount?: string; currency?: string }>();
  const last4 = typeof params.last4 === 'string' ? params.last4 : '';
  const amount = typeof params.amount === 'string' ? params.amount : '0';
  const currency = typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';
  const started = useRef(false);

  // Swallow Android hardware-back while the "bank" is confirming.
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => true);
    return () => sub.remove();
  }, []);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    (async () => {
      const minWait = new Promise((r) => setTimeout(r, MIN_SPINNER_MS));
      try {
        const phone = await getLastPhone();
        if (!phone) throw new Error('no_phone');
        if (!cardSimConfigured()) throw new Error('sim_not_configured');

        const res = await loadFromCard({
          phone,
          amount,
          currency,
          idempotencyKey: newCardLoadIdempotencyKey(),
        });
        await qc.invalidateQueries({ queryKey: qk.wallet() });
        await minWait;
        router.replace({
          pathname: '/cardload/success',
          params: {
            last4,
            amount: res.amount,
            currency: res.currency,
            reference: res.transaction_id.slice(0, 8).toUpperCase(),
          },
        });
      } catch (e) {
        await minWait;
        const reason =
          e instanceof Error && e.message === 'no_phone'
            ? 'Your session has no linked phone. Sign in again and retry.'
            : e instanceof Error && e.message === 'sim_not_configured'
              ? 'Top-up service is not configured in this build.'
              : cardLoadFailureReason(e);
        router.replace({
          pathname: '/cardload/failed',
          params: { last4, amount, currency, reason },
        });
      }
    })();
    // Fire exactly once on mount — params are frozen for this screen instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1} alignItems="center" justifyContent="center" padding={26} gap={22}>
          <ClaySurface
            depth="soft"
            radius={26}
            width={110}
            height={110}
            alignItems="center"
            justifyContent="center"
          >
            <ActivityIndicator size="large" color={colors.navy} />
          </ClaySurface>
          <YStack alignItems="center" gap={8}>
            <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={20} color={colors.text}>
              Confirming with your bank…
            </Text>
            <Text
              fontFamily="PlusJakartaSans-Medium"
              fontSize={13.5}
              color={colors.textMuted}
              textAlign="center"
            >
              Loading {formatMoney(amount, currency)} from card •••• {last4}.
            </Text>
          </YStack>
          <ClaySurface
            depth="soft"
            radius={16}
            flexDirection="row"
            alignItems="center"
            gap={10}
            paddingVertical={12}
            paddingHorizontal={16}
          >
            <Ionicons name="warning-outline" size={18} color={colors.danger} />
            <Text
              fontFamily="PlusJakartaSans-Bold"
              fontSize={12.5}
              color={colors.text}
              flexShrink={1}
            >
              Please don&apos;t go back or close the app while we process your top-up.
            </Text>
          </ClaySurface>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
