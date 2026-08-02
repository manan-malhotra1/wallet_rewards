/**
 * /cashin/amount — how much cash to load into the customer's wallet.
 *
 * Step 2 of the cash-in flow (mirrors /cashout/amount). Gradient header + step
 * indicator, a customer pill, a big amount display in the ACTIVE currency, a
 * white numeric keypad, and a Continue button. All money is rendered via
 * formatMoney(amount, currency) — never assume ZAR. The CurrencySelector lets
 * the agent pick which e-float wallet funds the deposit.
 *
 * Submit fires cashIn() WITHOUT a PIN first: below the tenant's step-up
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
import { CurrencySelector } from '@/components/forms/CurrencySelector';
import { ClayButton, ClayInset, ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { StepUpRequired } from '@/lib/api/errors';
import { cashIn, cashInFailureReason, newCashInIdempotencyKey } from '@/lib/api/cashin';
import { getMyWallet } from '@/lib/api/wallet';
import { qk } from '@/lib/query';
import { currencySymbol, formatMoney, maskPhone } from '@/lib/format';

/** Initials from the customer phone tail for the pill avatar. */
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

/** Amount entry screen — step 2 of cash-in. */
export default function CashInAmountScreen() {
  const router = useRouter();
  const colors = useColors();
  const qc = useQueryClient();
  const params = useLocalSearchParams<{ phone?: string; currency?: string }>();
  const customerPhone = typeof params.phone === 'string' ? params.phone : '';
  // `?currency=` seeds only the INITIAL selection; `selectedCurrency` (switchable
  // in-flow via CurrencySelector) is the source of truth for every money display
  // and the cashIn call thereafter — never assume ZAR. It selects which agent
  // e-float wallet funds the deposit.
  const paramCurrency =
    typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';
  const [selectedCurrency, setSelectedCurrency] = useState(paramCurrency);

  const [amount, setAmount] = useState('');
  const [busy, setBusy] = useState(false);
  const { data } = useQuery({ queryKey: qk.wallet(), queryFn: getMyWallet });

  // The agent's financial-wallet (e-float) currencies drive the in-flow selector.
  const walletCurrencies = (data?.accounts ?? [])
    .filter((a) => a.account_type === 'financial_wallet')
    .map((a) => a.currency);

  const wallet = data?.accounts.find(
    (a) => a.currency === selectedCurrency && a.account_type === 'financial_wallet',
  );
  const available = parseFloat(wallet?.available_balance ?? '0');
  const parsed = parseFloat(amount || '0');

  // Fee is quoted server-side and returned on the receipt, so we can't show an
  // exact "you fund" total here. Guard on the principal alone; the backend still
  // fails closed (409 InsufficientFloat) if amount + fee exceeds the e-float.
  const overdrawn = parsed > available;
  const canContinue = parsed > 0 && !overdrawn && !busy;
  const display = splitAmount(amount);
  const sym = currencySymbol(selectedCurrency);

  /**
   * Try-then-PIN entry point. Fire cashIn without a PIN so the backend's
   * step-up policy decides whether to demand one. The idempotency key persists
   * across the no-PIN attempt and (if needed) the PIN-bearing retry on
   * /cashin/pin — both rejections happen pre-ledger, so reusing the key is
   * safe and required.
   */
  async function onContinue() {
    if (!canContinue) return;
    const amountStr = parsed.toFixed(2);
    const idempotencyKey = newCashInIdempotencyKey();
    setBusy(true);
    try {
      const res = await cashIn({
        customerPhone,
        amount: amountStr,
        currency: selectedCurrency,
        idempotencyKey,
      });
      await qc.invalidateQueries({ queryKey: qk.wallet() });
      router.replace({
        pathname: '/cashin/success',
        params: {
          phone: customerPhone,
          amount: res.amount,
          fee: res.fee,
          commission: res.commission,
          currency: selectedCurrency,
          reference: (res.reference ?? res.transaction_id).slice(0, 8).toUpperCase(),
        },
      });
    } catch (e) {
      if (e instanceof StepUpRequired) {
        router.push({
          pathname: '/cashin/pin',
          params: {
            phone: customerPhone,
            amount: amountStr,
            currency: selectedCurrency,
            idem: idempotencyKey,
          },
        });
        return;
      }
      router.replace({
        pathname: '/cashin/failed',
        params: {
          phone: customerPhone,
          amount: amountStr,
          currency: selectedCurrency,
          reason: cashInFailureReason(e),
        },
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
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          <GradientHeader paddingBottom={22}>
            <HeaderBack title="Cash-in amount" />
            <StepIndicator step={2} caption="Step 2 of 3 · How much to load?" />
          </GradientHeader>

          {/* Customer pill. */}
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
                {tailInitials(customerPhone)}
              </Text>
            </View>
            <YStack flex={1} gap={2}>
              <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color={colors.text}>
                {maskPhone(customerPhone)}
              </Text>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color={colors.textMuted}>
                Customer
              </Text>
            </YStack>
            <View
              backgroundColor="#eaf1fb"
              paddingHorizontal={9}
              paddingVertical={4}
              borderRadius={20}
            >
              <XStack alignItems="center" gap={4}>
                <Ionicons name="person-outline" size={13} color={colors.navy} />
                <Text fontFamily="PlusJakartaSans-Bold" fontSize={11.5} color={colors.navy}>
                  Customer
                </Text>
              </XStack>
            </View>
          </ClaySurface>

          {/* Big amount display + balance hint. */}
          <YStack flex={1} alignItems="center" justifyContent="center" paddingHorizontal={22}>
            <CurrencySelector
              currencies={walletCurrencies}
              selected={selectedCurrency}
              onSelect={setSelectedCurrency}
              available={available}
            />
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
                  color={colors.textFaint}
                  marginTop={8}
                >
                  {sym.trim()}
                </Text>
                <Text
                  fontFamily="PlusJakartaSans-ExtraBold"
                  fontSize={56}
                  color={colors.text}
                  lineHeight={56}
                  letterSpacing={-1}
                >
                  {display.whole}
                  <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={56} color={colors.textFaint}>
                    {display.cents}
                  </Text>
                </Text>
              </XStack>
            </ClayInset>
            <Text
              fontFamily="PlusJakartaSans-Medium"
              fontSize={12}
              color={colors.textMuted}
              marginTop={16}
              textAlign="center"
            >
              Funded from your e-float. Your commission is shown on the receipt.
            </Text>
            {overdrawn ? (
              <Text
                fontFamily="PlusJakartaSans-Bold"
                color={colors.danger}
                fontSize={12.5}
                marginTop={8}
              >
                That&apos;s more than your e-float has right now.
              </Text>
            ) : null}
          </YStack>

          <NumericKeypad onPress={handleKey} />
          <View backgroundColor={colors.screenBg} paddingHorizontal={18} paddingBottom={18} paddingTop={4}>
            <ClayButton
              onPress={onContinue}
              disabled={!canContinue}
              loading={busy}
              accessibilityLabel="Continue"
            >
              {`Cash in ${formatMoney(parsed, selectedCurrency)}`}
            </ClayButton>
          </View>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
