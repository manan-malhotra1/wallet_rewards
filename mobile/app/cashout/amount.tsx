/**
 * /cashout/amount — how much cash to withdraw at the agent.
 *
 * Step 2 of the cash-out flow (mirrors /p2p/amount). Gradient header + step
 * indicator, an agent pill, a big amount display in the ACTIVE currency, a
 * white numeric keypad, and a Continue button. All money is rendered via
 * formatMoney(amount, currency) — never assume ZAR.
 *
 * Submit fires cashOut() WITHOUT a PIN first: below the tenant's step-up
 * threshold it completes immediately; on 401 `step_up_required` we route to
 * the PIN screen carrying the SAME idempotency key. Other failures route to
 * the failure screen with a friendly reason.
 */
import { useState } from 'react';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { StepIndicator } from '@/components/brand/StepIndicator';
import { NumericKeypad } from '@/components/forms/NumericKeypad';
import { ClayButton, ClayInset, ClaySurface } from '@/components/clay';
import { StepUpRequired } from '@/lib/api/errors';
import { cashOut, cashOutFailureReason, newCashOutIdempotencyKey } from '@/lib/api/cashout';
import { getMyWallet } from '@/lib/api/wallet';
import { qk } from '@/lib/query';
import { currencySymbol, formatMoney, maskPhone } from '@/lib/format';

/** Initials from the agent phone tail for the pill avatar. */
function tailInitials(phone: string): string {
  return phone.slice(-4).slice(0, 2);
}

/** Split an entered amount into [whole, cents] for the big display. */
function splitAmount(amount: string): { whole: string; cents: string } {
  const dot = amount.indexOf('.');
  if (dot === -1) return { whole: amount.length === 0 ? '0' : amount, cents: '.00' };
  return {
    whole: amount.slice(0, dot) || '0',
    cents: '.' + amount.slice(dot + 1).padEnd(2, '0').slice(0, 2),
  };
}

/** Amount entry screen — step 2 of cash-out. */
export default function CashOutAmountScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const params = useLocalSearchParams<{ phone?: string; currency?: string }>();
  const agentPhone = typeof params.phone === 'string' ? params.phone : '';
  const currency = typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';

  const [amount, setAmount] = useState('');
  const [busy, setBusy] = useState(false);
  const { data } = useQuery({ queryKey: qk.wallet(), queryFn: getMyWallet });

  const wallet = data?.accounts.find(
    (a) => a.currency === currency && a.account_type === 'financial_wallet',
  );
  const available = parseFloat(wallet?.available_balance ?? '0');
  const parsed = parseFloat(amount || '0');

  // Fee is quoted server-side and returned on the receipt, so we can't show an
  // exact "you pay" total here. Guard on the principal alone; the backend still
  // fails closed (409) if amount + fee exceeds the balance.
  const overdrawn = parsed > available;
  const canContinue = parsed > 0 && !overdrawn && !busy;
  const display = splitAmount(amount);
  const sym = currencySymbol(currency);

  /**
   * Try-then-PIN entry point. Fire cashOut without a PIN so the backend's
   * step-up policy decides whether to demand one. The idempotency key persists
   * across the no-PIN attempt and (if needed) the PIN-bearing retry on
   * /cashout/pin — both rejections happen pre-ledger, so reusing the key is
   * safe and required.
   */
  async function onContinue() {
    if (!canContinue) return;
    const amountStr = parsed.toFixed(2);
    const idempotencyKey = newCashOutIdempotencyKey();
    setBusy(true);
    try {
      const res = await cashOut({ agentPhone, amount: amountStr, currency, idempotencyKey });
      await qc.invalidateQueries({ queryKey: qk.wallet() });
      router.replace({
        pathname: '/cashout/success',
        params: {
          phone: agentPhone,
          amount: res.amount,
          fee: res.fee,
          currency,
          reference: (res.reference ?? res.transaction_id).slice(0, 8).toUpperCase(),
        },
      });
    } catch (e) {
      if (e instanceof StepUpRequired) {
        router.push({
          pathname: '/cashout/pin',
          params: { phone: agentPhone, amount: amountStr, currency, idem: idempotencyKey },
        });
        return;
      }
      router.replace({
        pathname: '/cashout/failed',
        params: { phone: agentPhone, amount: amountStr, currency, reason: cashOutFailureReason(e) },
      });
    } finally {
      setBusy(false);
    }
  }

  function handleKey(key: '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '.' | 'back') {
    if (key === 'back') {
      setAmount((a) => a.slice(0, -1));
      return;
    }
    if (key === '.') {
      if (amount.includes('.')) return;
      setAmount((a) => (a === '' ? '0.' : a + '.'));
      return;
    }
    setAmount((a) => {
      const dotAt = a.indexOf('.');
      if (dotAt !== -1 && a.length - dotAt - 1 >= 2) return a; // cap 2 decimals
      if (dotAt === -1 && a.length >= 7) return a; // cap whole digits
      return a + key;
    });
  }

  return (
    <View flex={1} backgroundColor="#ccd8e8">
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          <GradientHeader paddingBottom={22}>
            <HeaderBack title="Cash-out amount" />
            <StepIndicator step={2} caption="Step 2 of 3 · How much do you want in cash?" />
          </GradientHeader>

          {/* Agent pill. */}
          <ClaySurface
            depth="soft"
            radius={16}
            flexDirection="row"
            marginHorizontal={18}
            marginTop={16}
            alignItems="center"
            gap={11}
            padding={11}
          >
            <View
              width={40}
              height={40}
              borderRadius={20}
              backgroundColor="#50C0D0"
              alignItems="center"
              justifyContent="center"
            >
              <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#013a6b">
                {tailInitials(agentPhone)}
              </Text>
            </View>
            <YStack flex={1} gap={2}>
              <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color="#0c1b2a">
                {maskPhone(agentPhone)}
              </Text>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color="#8a98a6">
                Cash-out agent
              </Text>
            </YStack>
            <View
              backgroundColor="#eaf1fb"
              paddingHorizontal={9}
              paddingVertical={4}
              borderRadius={20}
            >
              <XStack alignItems="center" gap={4}>
                <Ionicons name="cash-outline" size={13} color="#00508F" />
                <Text fontFamily="PlusJakartaSans-Bold" fontSize={11.5} color="#00508F">
                  Agent
                </Text>
              </XStack>
            </View>
          </ClaySurface>

          {/* Big amount display + balance hint. */}
          <YStack flex={1} alignItems="center" justifyContent="center" paddingHorizontal={22}>
            <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#8a98a6">
              {currency} wallet · {formatMoney(available, currency)} available
            </Text>
            <ClayInset
              radius={24}
              marginTop={10}
              paddingVertical={16}
              paddingHorizontal={28}
              alignItems="center"
            >
              <XStack alignItems="flex-start" gap={4}>
                <Text
                  fontFamily="PlusJakartaSans-Bold"
                  fontSize={26}
                  color="#94a2b1"
                  marginTop={8}
                >
                  {sym.trim()}
                </Text>
                <Text
                  fontFamily="PlusJakartaSans-ExtraBold"
                  fontSize={56}
                  color="#0c1b2a"
                  lineHeight={56}
                  letterSpacing={-1}
                >
                  {display.whole}
                  <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={56} color="#cfd9e3">
                    {display.cents}
                  </Text>
                </Text>
              </XStack>
            </ClayInset>
            <Text
              fontFamily="PlusJakartaSans-Medium"
              fontSize={12}
              color="#8a98a6"
              marginTop={16}
              textAlign="center"
            >
              A withdrawal fee applies and is shown on your receipt.
            </Text>
            {overdrawn ? (
              <Text
                fontFamily="PlusJakartaSans-Bold"
                color="#c0392b"
                fontSize={12.5}
                marginTop={8}
              >
                That&apos;s more than your wallet has right now.
              </Text>
            ) : null}
          </YStack>

          <NumericKeypad onPress={handleKey} />
          <View backgroundColor="#ccd8e8" paddingHorizontal={18} paddingBottom={18} paddingTop={4}>
            <ClayButton
              onPress={onContinue}
              disabled={!canContinue}
              loading={busy}
              accessibilityLabel="Continue"
            >
              {`Cash out ${formatMoney(parsed, currency)}`}
            </ClayButton>
          </View>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
