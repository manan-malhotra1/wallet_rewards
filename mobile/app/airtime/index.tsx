/**
 * /airtime — buy prepaid airtime (Epic 17).
 *
 * Pick the number to top up (PhoneInput or a quick-pick list, mirroring the
 * P2P recipient screen), the carrier network, and an amount, then "Buy
 * airtime". The result routes to a dedicated receipt screen — success /
 * pending / failed — exactly like the P2P and cash-in flows.
 *
 * The quick-pick list doubles as the SIMULATOR cheat-sheet: the backend's
 * SimulatorProvider is deterministic by msisdn suffix (…0001 → provider
 * fails and the debit is reversed; …0002 → stays PENDING awaiting the
 * provider callback; anything else vends instantly), so the list carries
 * numbers for each outcome with a hint label.
 *
 * The wallet to debit defaults to ZAR (falling back to the user's first wallet
 * currency if they hold no ZAR wallet) and is switchable in-flow via the shared
 * CurrencySelector, mirroring the P2P / cash-out flows.
 */
import { useEffect, useRef, useState } from 'react';
import {
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
  TouchableWithoutFeedback,
} from 'react-native';
import { useRouter } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { PhoneInput } from '@/components/forms/PhoneInput';
import { CurrencySelector, defaultWalletCurrency } from '@/components/forms/CurrencySelector';
import { PointsDiscount } from '@/components/forms/PointsDiscount';
import { ClayButton, ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { ApiError } from '@/lib/api/errors';
import { buyAirtime, newAirtimeIdempotencyKey } from '@/lib/api/airtime';
import {
  getConversionRates,
  pointsToFiat,
  redeemPointsToWallet,
} from '@/lib/api/redemption';
import { getMyWallet } from '@/lib/api/wallet';
import { qk } from '@/lib/query';
import { maskPhone } from '@/lib/format';

/** Selectable carrier networks. Sent verbatim as the `network` string. */
const NETWORKS = ['MTN', 'Vodacom', 'Cell C', 'Telkom'] as const;

/** Quick-pick airtime amounts (whole units of the wallet currency). */
const QUICK_AMOUNTS = [10, 20, 50, 100] as const;

/**
 * Quick-pick recharge numbers — the airtime mirror of P2P's RECENTS list.
 * The hints map to the backend SimulatorProvider's magic suffixes
 * (…0001 fails, …0002 stays pending); the rest vend instantly.
 */
const QUICK_NUMBERS = [
  { initials: 'TC', name: 'Tariro', phone: '+263786612093', hint: 'Delivers instantly', bg: '#fff7e6', fg: '#c98a00' },
  { initials: 'RS', name: 'Rudo', phone: '+263787715040', hint: 'Delivers instantly', bg: '#fdeef0', fg: '#c0455a' },
  { initials: 'AL', name: 'Alice', phone: '+27825550001', hint: 'Test: provider fails, refund issued', bg: '#50C0D0', fg: '#013a6b' },
  { initials: 'BB', name: 'Bob', phone: '+27825550002', hint: 'Test: stays pending (callback)', bg: '#eef3fb', fg: '#00508F' },
] as const;

/**
 * Map a thrown error to a friendly failure-screen reason.
 *
 * Typed API errors carry an HTTP status we branch on: 409 insufficient funds,
 * 403 not permitted, 422 validation / no airtime merchant. Everything else
 * falls back to the server message or a generic line.
 */
function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 409) return 'Not enough funds in your wallet.';
    if (e.status === 403) return "Your account isn't permitted to buy airtime.";
    if (e.status === 422) return e.message || 'Check the number and amount, then try again.';
    return e.message || 'Airtime purchase failed.';
  }
  return 'Airtime purchase failed. Please try again.';
}

/** Airtime top-up screen — number, network, amount → receipt route. */
export default function AirtimeScreen() {
  const router = useRouter();
  const colors = useColors();
  const qc = useQueryClient();

  const [phone, setPhone] = useState('');
  // Name of the tapped quick-pick, shown as a selected pill. Cleared when the
  // user types in the PhoneInput (manual entry overrides the pick).
  const [pickedName, setPickedName] = useState<string | null>(null);
  const [network, setNetwork] = useState<string>(NETWORKS[0]);
  const [amount, setAmount] = useState('');
  // Points the buyer is applying to this recharge (0 = not using points).
  const [points, setPoints] = useState(0);
  const [busy, setBusy] = useState(false);
  // Wallet to debit — defaults to ZAR, reconciled to the ZAR-preferred default
  // once the wallet loads. Switchable in-flow via the CurrencySelector.
  const [currency, setCurrency] = useState('ZAR');
  const { data: wallet } = useQuery({ queryKey: qk.wallet(), queryFn: getMyWallet });
  const walletCurrencies = (wallet?.accounts ?? [])
    .filter((a) => a.account_type === 'financial_wallet')
    .map((a) => a.currency);
  const available = parseFloat(
    wallet?.accounts.find(
      (a) => a.currency === currency && a.account_type === 'financial_wallet',
    )?.available_balance ?? '0',
  );

  // Active conversion rates + PTS balance drive the "pay with points" option;
  // a failure just hides it (points never block buying airtime).
  const { data: rates } = useQuery({
    queryKey: qk.conversionRates(),
    queryFn: getConversionRates,
    staleTime: 300_000,
  });
  const rate = rates?.find((r) => r.currency === currency) ?? null;
  const pointsBalance = parseFloat(
    wallet?.accounts.find((a) => a.currency === 'PTS')?.available_balance ?? '0',
  );

  // Reconcile the default once the wallet resolves: if the selection isn't a
  // currency the user holds, snap to the ZAR-preferred default. A manual pick
  // is always in the list, so this never overrides the user's own choice.
  useEffect(() => {
    if (walletCurrencies.length > 0 && !walletCurrencies.includes(currency)) {
      setCurrency(defaultWalletCurrency(walletCurrencies));
    }
  }, [walletCurrencies, currency]);

  // Idempotency key for the CURRENT attempt. Held in a ref so a retry after an
  // error reuses the same key (the backend dedups a replay). Reset whenever an
  // input changes — a changed request is a new attempt.
  const idemRef = useRef<string | null>(null);

  const parsed = parseFloat(amount || '0');
  const phoneDigits = phone.replace(/\D/g, '');
  const canBuy = phoneDigits.length >= 9 && parsed > 0 && !busy;

  /** Reset the pending idempotency key + points when any input changes.
   *  The points ceiling depends on the amount and currency, so a stale
   *  selection could exceed it. */
  function resetAttempt() {
    idemRef.current = null;
    setPoints((p) => (p === 0 ? p : 0));
  }

  function handlePhone(next: string) {
    setPhone(next);
    setPickedName(null);
    resetAttempt();
  }

  function handlePick(name: string, e164: string) {
    setPhone(e164);
    setPickedName(name);
    resetAttempt();
  }

  function handleNetwork(next: string) {
    setNetwork(next);
    resetAttempt();
  }

  function handleCurrency(next: string) {
    setCurrency(next);
    resetAttempt();
  }

  function handleAmount(next: string) {
    // Keep digits + a single dot, cap cents at 2 places.
    const cleaned = next.replace(/[^0-9.]/g, '');
    const dot = cleaned.indexOf('.');
    const normalized =
      dot === -1 ? cleaned : cleaned.slice(0, dot + 1) + cleaned.slice(dot + 1).replace(/\./g, '').slice(0, 2);
    setAmount(normalized);
    resetAttempt();
  }

  /**
   * Submit the buy, then route to the matching receipt screen:
   * COMPLETED → /airtime/success, PENDING → /airtime/pending (carries the
   * recharge id so that screen can re-poll), REVERSED / thrown → /airtime/failed.
   * The wallet query is invalidated on any outcome that debited (success or
   * pending reservation) so /home shows the fresh balance.
   */
  async function onBuy() {
    if (!canBuy) return;
    Keyboard.dismiss();
    if (idemRef.current === null) idemRef.current = newAirtimeIdempotencyKey();
    setBusy(true);
    const amountStr = parsed.toFixed(2);
    const base = { msisdn: phone, network, amount: amountStr, currency };
    try {
      // Redeem FIRST so the wallet is topped up before the full-amount debit.
      // Key derived from the buy's, so a retry replays the SAME redemption
      // (backend fast-path) rather than burning points twice.
      if (points > 0) {
        await redeemPointsToWallet({
          points: String(points),
          currency,
          idempotencyKey: `${idemRef.current}:points`,
        });
      }
      const result = await buyAirtime({ ...base, idempotencyKey: idemRef.current });
      await qc.invalidateQueries({ queryKey: qk.wallet() });
      // Points moved too when the payment used them — refresh the
      // rewards-side ledger so the chip + history agree with the wallet.
      await qc.invalidateQueries({ queryKey: qk.pointsHistory() });
      if (result.status === 'COMPLETED') {
        idemRef.current = null; // terminal — a future buy is a new attempt
        router.replace({
          pathname: '/airtime/success',
          params: {
            ...base,
            reference:
              result.provider_reference ?? result.transaction_id.slice(0, 8).toUpperCase(),
          },
        });
      } else if (result.status === 'PENDING') {
        router.replace({
          pathname: '/airtime/pending',
          params: { ...base, id: result.id },
        });
      } else {
        // REVERSED — the debit was refunded server-side.
        idemRef.current = null;
        router.replace({
          pathname: '/airtime/failed',
          params: {
            ...base,
            reason:
              result.failure_reason === 'simulated_provider_failure'
                ? 'The carrier could not deliver this recharge.'
                : result.failure_reason || 'The recharge was reversed. No airtime was delivered.',
          },
        });
      }
    } catch (e) {
      // Keep idemRef so a retry from the failed screen replays the same key.
      router.replace({
        pathname: '/airtime/failed',
        params: { ...base, reason: errorMessage(e) },
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <KeyboardAvoidingView
          style={{ flex: 1 }}
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        >
          <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
            <ScrollView
              contentContainerStyle={{ flexGrow: 1, paddingBottom: 28 }}
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator={false}
              bounces={false}
            >
              <GradientHeader paddingBottom={24}>
                <HeaderBack title="Buy airtime" />
                <Text
                  fontFamily="PlusJakartaSans-Medium"
                  fontSize={12.5}
                  color="rgba(255,255,255,0.85)"
                  marginTop={10}
                >
                  Top up any mobile number instantly.
                </Text>
              </GradientHeader>

              <YStack padding={22} paddingTop={20} gap={18}>
                {/* Number to recharge — manual entry or a quick-pick below. */}
                <PhoneInput onChange={handlePhone} variant="focused" />

                {/* Selected quick-pick pill (manual typing clears it). */}
                {pickedName ? (
                  <XStack
                    alignSelf="flex-start"
                    alignItems="center"
                    gap={8}
                    backgroundColor="#eaf1fb"
                    paddingHorizontal={12}
                    paddingVertical={7}
                    borderRadius={18}
                  >
                    <Ionicons name="call" size={13} color={colors.navy} />
                    <Text fontFamily="PlusJakartaSans-Bold" fontSize={12.5} color={colors.navy}>
                      {pickedName} · {maskPhone(phone)}
                    </Text>
                    <Pressable onPress={() => handlePick('', '')} accessibilityLabel="Clear picked number">
                      <Ionicons name="close-circle" size={16} color={colors.navy} />
                    </Pressable>
                  </XStack>
                ) : null}

                {/* Quick-pick numbers — the airtime mirror of P2P's recents. */}
                <YStack gap={8}>
                  <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={14} color={colors.text}>
                    Recharge again
                  </Text>
                  <ClaySurface depth="soft" radius={18} paddingHorizontal={14}>
                    {QUICK_NUMBERS.map((r, i) => (
                      <Pressable
                        key={r.phone}
                        onPress={() => handlePick(r.name, r.phone)}
                        accessibilityRole="button"
                        accessibilityLabel={`Recharge ${r.name}`}
                        style={({ pressed }) => ({ opacity: pressed ? 0.6 : 1 })}
                      >
                        <XStack
                          alignItems="center"
                          gap={12}
                          paddingVertical={12}
                          borderBottomWidth={i === QUICK_NUMBERS.length - 1 ? 0 : 1}
                          borderBottomColor={colors.hairline}
                        >
                          <View
                            width={42}
                            height={42}
                            borderRadius={21}
                            backgroundColor={r.bg}
                            alignItems="center"
                            justifyContent="center"
                          >
                            <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color={r.fg}>
                              {r.initials}
                            </Text>
                          </View>
                          <YStack flex={1} gap={1}>
                            <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color={colors.text}>
                              {r.name}
                            </Text>
                            <Text
                              fontFamily="PlusJakartaSans-Medium"
                              fontSize={11.5}
                              color={colors.textMuted}
                            >
                              {r.phone} · {r.hint}
                            </Text>
                          </YStack>
                          <Text fontSize={18} color={colors.textFaint}>›</Text>
                        </XStack>
                      </Pressable>
                    ))}
                  </ClaySurface>
                </YStack>

                {/* Network selector — plain string chips. */}
                <YStack gap={8}>
                  <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12} color={colors.textMuted}>
                    Network
                  </Text>
                  <XStack gap={8} flexWrap="wrap">
                    {NETWORKS.map((n) => {
                      const selected = network === n;
                      return (
                        <Pressable
                          key={n}
                          onPress={() => handleNetwork(n)}
                          accessibilityRole="button"
                          accessibilityLabel={`Network ${n}`}
                        >
                          <View
                            paddingHorizontal={16}
                            paddingVertical={9}
                            borderRadius={20}
                            backgroundColor={selected ? colors.navy : colors.rim}
                            borderWidth={1.5}
                            borderColor={selected ? colors.navy : colors.hairline}
                          >
                            <Text
                              fontFamily="PlusJakartaSans-Bold"
                              fontSize={13}
                              color={selected ? colors.textOnDark : colors.navy}
                            >
                              {n}
                            </Text>
                          </View>
                        </Pressable>
                      );
                    })}
                  </XStack>
                </YStack>

                {/* Amount. Currency selector defaults to ZAR and lets the user
                    pick which wallet is debited (parity with P2P / cash-out). */}
                <YStack gap={8}>
                  <XStack alignItems="center" justifyContent="space-between" gap={10}>
                    <Text
                      fontFamily="PlusJakartaSans-SemiBold"
                      fontSize={12}
                      color={colors.textMuted}
                    >
                      Amount ({currency})
                    </Text>
                    <View flexShrink={1}>
                      <CurrencySelector
                        currencies={walletCurrencies}
                        selected={currency}
                        onSelect={handleCurrency}
                        available={available}
                      />
                    </View>
                  </XStack>
                  <XStack
                    alignItems="center"
                    gap={8}
                    borderWidth={1.5}
                    borderColor={colors.hairline}
                    borderRadius={16}
                    paddingHorizontal={14}
                    height={54}
                    backgroundColor={colors.clayInset}
                  >
                    <Text fontFamily="PlusJakartaSans-Bold" fontSize={15} color={colors.textFaint}>
                      {currency}
                    </Text>
                    <View width={1} height={22} backgroundColor={colors.hairline} />
                    <TextInput
                      value={amount}
                      onChangeText={handleAmount}
                      keyboardType="decimal-pad"
                      placeholder="0.00"
                      placeholderTextColor={colors.textFaint}
                      style={{
                        flex: 1,
                        paddingVertical: 8,
                        fontSize: 15,
                        fontFamily: 'PlusJakartaSans-Medium',
                        color: colors.text,
                      }}
                      accessibilityLabel="Airtime amount"
                    />
                  </XStack>
                  <XStack gap={8} flexWrap="wrap">
                    {QUICK_AMOUNTS.map((n) => {
                      const value = n.toFixed(2);
                      const selected = amount === value;
                      return (
                        <Pressable
                          key={n}
                          onPress={() => handleAmount(selected ? '' : value)}
                          accessibilityLabel={`Set amount ${n}`}
                        >
                          <View
                            paddingHorizontal={13}
                            paddingVertical={6}
                            borderRadius={18}
                            backgroundColor={selected ? colors.navy : '#eef3fb'}
                          >
                            <Text
                              fontFamily="PlusJakartaSans-Bold"
                              fontSize={12}
                              color={selected ? colors.textOnDark : colors.navy}
                            >
                              {currency} {n}
                            </Text>
                          </View>
                        </Pressable>
                      );
                    })}
                  </XStack>
                </YStack>

                <PointsDiscount
                  rate={rate}
                  balance={pointsBalance}
                  txnAmount={parsed}
                  currency={currency}
                  points={points}
                  onChange={setPoints}
                />

                <ClayButton
                  onPress={onBuy}
                  disabled={!canBuy}
                  loading={busy}
                  accessibilityLabel="Buy airtime"
                >
                  {busy
                    ? 'Processing…'
                    : parsed > 0
                      ? points > 0 && rate
                        ? `Buy ${currency} ${parsed.toFixed(2)} · pay ${currency} ${Math.max(
                            0,
                            parsed - pointsToFiat(points, rate),
                          ).toFixed(2)}`
                        : `Buy ${currency} ${parsed.toFixed(2)} airtime`
                      : 'Buy airtime'}
                </ClayButton>
              </YStack>
            </ScrollView>
          </TouchableWithoutFeedback>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
