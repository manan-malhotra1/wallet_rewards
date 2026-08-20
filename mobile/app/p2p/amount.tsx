/**
 * /p2p/amount — amount entry (Sasai Pay redesign).
 *
 * Step 2 of the send-money flow. Gradient header with step indicator,
 * recipient pill (avatar + name + verified badge), big amount display
 * with cents in a muted tint, quick-amount chips ($10 / $25 / $50 /
 * $100), fee + "Recipient gets X" line, then a white numeric keypad
 * pinned to the bottom. Continue routes to /p2p/pin.
 */
import { useState } from 'react';
import { Pressable } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { StepIndicator } from '@/components/brand/StepIndicator';
import { NumericKeypad } from '@/components/forms/NumericKeypad';
import { PointsDiscount } from '@/components/forms/PointsDiscount';
import { CurrencySelector } from '@/components/forms/CurrencySelector';
import { ClayButton, ClayInset, ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { ApiError, RateLimited, StepUpRequired } from '@/lib/api/errors';
import { newP2PIdempotencyKey, sendP2P } from '@/lib/api/payments';
import { quoteServiceFee } from '@/lib/api/pricing';
import {
  getConversionRates,
  pointsToFiat,
  redeemPointsToWallet,
} from '@/lib/api/redemption';
import { getMyWallet } from '@/lib/api/wallet';
import { qk } from '@/lib/query';
import { currencySymbol, formatMoney, maskPhone } from '@/lib/format';

const CHIPS = [50, 100, 200, 500] as const;

/** Returns initials from a phone tail or recipient name for the pill avatar. */
function tailInitials(phone: string): string {
  const tail = phone.slice(-4);
  return tail.slice(0, 2);
}

/** Format an entered amount as a [whole, cents] pair for the big display. */
function splitAmount(amount: string): { whole: string; cents: string; hasDot: boolean } {
  const dot = amount.indexOf('.');
  if (dot === -1) {
    return {
      whole: amount.length === 0 ? '0' : amount,
      cents: '.00',
      hasDot: false,
    };
  }
  return {
    whole: amount.slice(0, dot) || '0',
    cents: '.' + (amount.slice(dot + 1).padEnd(2, '0').slice(0, 2)),
    hasDot: true,
  };
}

/** Amount entry screen. */
export default function AmountScreen() {
  const router = useRouter();
  const colors = useColors();
  const qc = useQueryClient();
  const params = useLocalSearchParams<{ phone: string; currency?: string }>();
  const recipientPhone = typeof params.phone === 'string' ? params.phone : '';
  // Active wallet currency threaded from /home via /p2p/recipient, used only as
  // the INITIAL selection. Defaults to ZAR when the param is absent so the flow
  // still works. From here on `selectedCurrency` (switchable in-flow via the
  // CurrencySelector) is the source of truth for every money display and the
  // sendP2P call — never assume ZAR.
  const paramCurrency = typeof params.currency === 'string' ? params.currency : 'ZAR';
  const [selectedCurrency, setSelectedCurrency] = useState(paramCurrency);
  const [amount, setAmount] = useState('');
  // Points the sender is applying to this payment (0 = not using points).
  const [points, setPoints] = useState(0);
  const [busy, setBusy] = useState(false);
  const { data } = useQuery({ queryKey: qk.wallet(), queryFn: getMyWallet });

  // The user's financial-wallet currencies drive the in-flow selector.
  const walletCurrencies = (data?.accounts ?? [])
    .filter((a) => a.account_type === 'financial_wallet')
    .map((a) => a.currency);

  // Active conversion rates + the PTS balance drive the "pay with points"
  // option. Both are best-effort: a failure just hides the option (points are
  // a sweetener, never a blocker for sending money).
  const { data: rates } = useQuery({
    queryKey: qk.conversionRates(),
    queryFn: getConversionRates,
    staleTime: 300_000,
  });
  const rate = rates?.find((r) => r.currency === selectedCurrency) ?? null;
  const pointsBalance = parseFloat(
    data?.accounts.find((a) => a.currency === 'PTS')?.available_balance ?? '0',
  );

  const symbol = currencySymbol(selectedCurrency).trim();
  const wallet = data?.accounts.find(
    (a) => a.currency === selectedCurrency && a.account_type === 'financial_wallet',
  );
  const available = parseFloat(wallet?.available_balance ?? '0');
  const parsed = parseFloat(amount || '0');

  // Live fee preview from the backend so the confirmation line matches what
  // the sender is actually charged (the fee can be fixed or %-based per the
  // tenant's pricing config). Quoted per entered amount; cached by react-query.
  const amountKey = parsed > 0 ? parsed.toFixed(2) : '';
  const { data: quote } = useQuery({
    queryKey: ['fee-quote', 'p2p', amountKey],
    queryFn: () => quoteServiceFee('p2p', amountKey),
    enabled: parsed > 0,
    staleTime: 60_000,
  });
  const fee = quote ? parseFloat(quote.fee) : 0;
  const total = parsed + fee;

  // Points are redeemed into the wallet BEFORE the payment is charged, so the
  // wallet effectively only needs (total − discount) available.
  const discount = rate && points > 0 ? pointsToFiat(points, rate) : 0;
  const payable = Math.max(0, total - discount);

  // Overdraft must account for the fee — the wallet is debited amount + fee,
  // less whatever the points top it up by first.
  const overdrawn = payable > available;
  const canContinue = parsed > 0 && !overdrawn && !busy;
  const display = splitAmount(amount);

  /** A changed amount / currency invalidates the points ceiling — reset it. */
  function resetPoints() {
    if (points !== 0) setPoints(0);
  }

  /**
   * Try-then-PIN entry point. We fire /payments/p2p without a PIN first
   * so the backend's step-up policy decides whether to demand one. The
   * idempotency key persists across the no-PIN attempt and (if needed)
   * the PIN-bearing retry on /p2p/pin — both rejections happen
   * pre-ledger, so reusing the same key is safe and required.
   */
  async function onContinue() {
    if (!canContinue) return;
    const amountStr = parsed.toFixed(2);
    const idempotencyKey = newP2PIdempotencyKey();
    setBusy(true);
    try {
      // Redeem FIRST so the wallet is topped up before the full-amount debit.
      // The key is derived from the payment's, so a step-up retry replays the
      // SAME redemption (backend fast-path) instead of burning points twice.
      if (points > 0) {
        await redeemPointsToWallet({
          points: String(points),
          currency: selectedCurrency,
          idempotencyKey: `${idempotencyKey}:points`,
        });
      }
      const res = await sendP2P({
        recipientPhone,
        amount: amountStr,
        currency: selectedCurrency,
        idempotencyKey,
      });
      // Below step-up threshold → backend let it through without a PIN.
      await qc.invalidateQueries({ queryKey: qk.wallet() });
      // Points moved too when the payment used them — refresh the
      // rewards-side ledger so the chip + history agree with the wallet.
      await qc.invalidateQueries({ queryKey: qk.pointsHistory() });
      router.replace({
        pathname: '/p2p/success',
        params: {
          phone: recipientPhone,
          amount: amountStr,
          earned: String(res.earned_points ?? 0),
          reference: res.transaction_id.slice(0, 8).toUpperCase(),
        },
      });
    } catch (e) {
      if (e instanceof StepUpRequired) {
        // Above threshold — route to PIN screen, carry the key + points
        // forward so the retry redeems (idempotently) and pays under a PIN.
        router.push({
          pathname: '/p2p/pin' as never,
          params: {
            phone: recipientPhone,
            amount: amountStr,
            currency: selectedCurrency,
            idem: idempotencyKey,
            points: String(points),
          },
        });
        return;
      }
      const reason =
        e instanceof RateLimited
          ? 'Too many attempts. Try again later.'
          : e instanceof ApiError
            ? e.message
            : 'Payment failed.';
      router.replace({
        pathname: '/p2p/failed' as never,
        params: { phone: recipientPhone, amount: amountStr, reason },
      });
    } finally {
      setBusy(false);
    }
  }

  function handleKey(key: '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '.' | 'back') {
    if (key === 'back') {
      resetPoints();
      setAmount((a) => a.slice(0, -1));
      return;
    }
    if (key === '.') {
      if (amount.includes('.')) return;
      resetPoints();
      setAmount((a) => (a === '' ? '0.' : a + '.'));
      return;
    }
    resetPoints();
    setAmount((a) => {
      const dotAt = a.indexOf('.');
      // Cap cents at 2 digits.
      if (dotAt !== -1 && a.length - dotAt - 1 >= 2) return a;
      // Cap whole digits at 7 (R 9,999,999.99).
      if (dotAt === -1 && a.length >= 7) return a;
      return a + key;
    });
  }

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          <GradientHeader paddingBottom={22}>
            <HeaderBack title="Enter amount" />
            <StepIndicator step={2} caption="Step 2 of 3 · How much are you sending?" />
          </GradientHeader>

          {/* Recipient pill — overlaps the header slightly. */}
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
                {tailInitials(recipientPhone)}
              </Text>
            </View>
            <YStack flex={1} gap={2}>
              <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color={colors.text}>
                {maskPhone(recipientPhone)}
              </Text>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color={colors.textMuted}>
                Sasai user
              </Text>
            </YStack>
            <View
              backgroundColor="#e7f6ee"
              paddingHorizontal={9}
              paddingVertical={4}
              borderRadius={20}
            >
              <Text fontFamily="PlusJakartaSans-Bold" fontSize={11.5} color={colors.success}>
                Verified
              </Text>
            </View>
          </ClaySurface>

          {/* Big amount display + balance hint + chips. */}
          <YStack flex={1} alignItems="center" justifyContent="center" paddingHorizontal={22}>
            <CurrencySelector
              currencies={walletCurrencies}
              selected={selectedCurrency}
              onSelect={(c) => {
                resetPoints();
                setSelectedCurrency(c);
              }}
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
                  {symbol}
                </Text>
                <Text
                  fontFamily="PlusJakartaSans-ExtraBold"
                  fontSize={56}
                  color={colors.text}
                  lineHeight={56}
                  letterSpacing={-1}
                >
                  {display.whole}
                  <Text
                    fontFamily="PlusJakartaSans-ExtraBold"
                    fontSize={56}
                    color={colors.textFaint}
                  >
                    {display.cents}
                  </Text>
                </Text>
              </XStack>
            </ClayInset>
            <XStack gap={8} marginTop={18} flexWrap="wrap" justifyContent="center">
              {CHIPS.map((n) => {
                const value = n.toFixed(2);
                const selected = amount === value;
                return (
                  <Pressable
                    key={n}
                    onPress={() => setAmount(selected ? '' : value)}
                    accessibilityLabel={`Set amount ${symbol}${n}`}
                  >
                    <View
                      paddingHorizontal={14}
                      paddingVertical={7}
                      borderRadius={20}
                      backgroundColor={selected ? colors.navy : colors.rim}
                    >
                      <Text
                        fontFamily="PlusJakartaSans-Bold"
                        fontSize={12.5}
                        color={selected ? colors.textOnDark : colors.navy}
                      >
                        {symbol}{n}
                      </Text>
                    </View>
                  </Pressable>
                );
              })}
            </XStack>
            <View width="100%" marginTop={16}>
              <PointsDiscount
                rate={rate}
                balance={pointsBalance}
                txnAmount={total}
                currency={selectedCurrency}
                points={points}
                onChange={setPoints}
              />
            </View>
            <Text fontFamily="PlusJakartaSans-Medium" fontSize={12} color={colors.textMuted} marginTop={16}>
              Fee {formatMoney(fee, selectedCurrency)} · You pay{' '}
              <Text fontFamily="PlusJakartaSans-Bold" color={colors.text}>
                {formatMoney(payable, selectedCurrency)}
              </Text>
              {discount > 0 ? (
                <Text fontFamily="PlusJakartaSans-Medium" color={colors.textMuted}>
                  {' '}
                  ({formatMoney(discount, selectedCurrency)} from points)
                </Text>
              ) : null}
            </Text>
            {overdrawn ? (
              <Text
                fontFamily="PlusJakartaSans-Bold"
                color={colors.danger}
                fontSize={12.5}
                marginTop={8}
              >
                That's more than your wallet has right now.
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
              {`Send ${formatMoney(parsed, selectedCurrency)}`}
            </ClayButton>
          </View>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
