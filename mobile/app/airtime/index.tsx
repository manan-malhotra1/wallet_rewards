/**
 * /airtime — buy prepaid airtime (Epic 17).
 *
 * A single self-contained screen: pick the number to top up (PhoneInput),
 * the carrier network (clay chips), and an amount, then "Buy airtime". The
 * result is shown INLINE on the same screen — we deliberately do NOT navigate
 * to a separate pending/receipt route, because airtime resolves synchronously
 * often enough that an in-place success/failure panel feels instant.
 *
 * The buy calls `buyAirtime`, which fires the recharge and — when the provider
 * is still PENDING — polls once for a terminal status before returning, so the
 * inline panel usually lands on COMPLETED/REVERSED rather than a spinner.
 *
 * `currency` from the route params is DISPLAY-ONLY (the backend resolves the
 * real currency server-side); we only use it to label the amount field.
 */
import { useRef, useState } from 'react';
import {
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
  TouchableWithoutFeedback,
} from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { PhoneInput } from '@/components/forms/PhoneInput';
import { ClayButton, ClaySurface } from '@/components/clay';
import { ApiError } from '@/lib/api/errors';
import {
  buyAirtime,
  newAirtimeIdempotencyKey,
  type AirtimeResult,
} from '@/lib/api/airtime';
import { maskPhone } from '@/lib/format';

/** Selectable carrier networks. Sent verbatim as the `network` string. */
const NETWORKS = ['MTN', 'Vodacom', 'Cell C', 'Telkom'] as const;

/** Quick-pick airtime amounts (whole units of the wallet currency). */
const QUICK_AMOUNTS = [10, 20, 50, 100] as const;

/**
 * Inline outcome state for the buy. `null` = nothing shown yet; otherwise a
 * kind + message pair the panel renders.
 */
type Outcome =
  | { kind: 'success'; result: AirtimeResult }
  | { kind: 'processing'; result: AirtimeResult }
  | { kind: 'error'; message: string }
  | null;

/**
 * Map a thrown error (or a REVERSED result) to a friendly inline message.
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

/** Airtime top-up screen. */
export default function AirtimeScreen() {
  const params = useLocalSearchParams<{ currency?: string }>();
  const currency = typeof params.currency === 'string' && params.currency ? params.currency : 'ZAR';

  const [phone, setPhone] = useState('');
  const [network, setNetwork] = useState<string>(NETWORKS[0]);
  const [amount, setAmount] = useState('');
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);

  // Idempotency key for the CURRENT attempt. Held in a ref so a retry after an
  // error reuses the same key (the backend dedups a replay). It is reset to
  // null whenever an input changes — a changed request is a new attempt and
  // must not collide with the previous key.
  const idemRef = useRef<string | null>(null);

  const parsed = parseFloat(amount || '0');
  const phoneDigits = phone.replace(/\D/g, '');
  const canBuy = phoneDigits.length >= 9 && parsed > 0 && !busy;

  /** Reset the pending idempotency key + any stale outcome when inputs change. */
  function resetAttempt() {
    idemRef.current = null;
    setOutcome(null);
  }

  function handlePhone(next: string) {
    setPhone(next);
    resetAttempt();
  }

  function handleNetwork(next: string) {
    setNetwork(next);
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
   * Submit the buy and render the outcome inline.
   *
   * Reuses the ref-held idempotency key so a post-error retry is a safe replay.
   * Branches the returned recharge on `status`: COMPLETED → success panel,
   * PENDING (after the single poll) → processing panel with the reference,
   * anything else (REVERSED/failed) → error panel.
   */
  async function onBuy() {
    if (!canBuy) return;
    Keyboard.dismiss();
    if (idemRef.current === null) idemRef.current = newAirtimeIdempotencyKey();
    setBusy(true);
    setOutcome(null);
    try {
      const result = await buyAirtime({
        msisdn: phone,
        network,
        amount: parsed.toFixed(2),
        idempotencyKey: idemRef.current,
      });
      if (result.status === 'COMPLETED') {
        setOutcome({ kind: 'success', result });
        // A terminal success shouldn't be replayed under the same key if the
        // user buys again — mint a fresh one next time.
        idemRef.current = null;
      } else if (result.status === 'PENDING') {
        setOutcome({ kind: 'processing', result });
      } else {
        // REVERSED / failed — funds (if reserved) are refunded server-side.
        setOutcome({
          kind: 'error',
          message: result.failure_reason || 'The recharge was reversed. No airtime was delivered.',
        });
      }
    } catch (e) {
      // Keep idemRef so "Try again" replays under the same key.
      setOutcome({ kind: 'error', message: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <View flex={1} backgroundColor="#ccd8e8">
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
                {/* Number to recharge. */}
                <PhoneInput onChange={handlePhone} variant="focused" />

                {/* Network selector — plain string chips. */}
                <YStack gap={8}>
                  <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12} color="#5a6b7b">
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
                            backgroundColor={selected ? '#00508F' : '#e9f1f9'}
                            borderWidth={1.5}
                            borderColor={selected ? '#00508F' : 'rgba(1,46,84,0.08)'}
                          >
                            <Text
                              fontFamily="PlusJakartaSans-Bold"
                              fontSize={13}
                              color={selected ? '#ffffff' : '#00508F'}
                            >
                              {n}
                            </Text>
                          </View>
                        </Pressable>
                      );
                    })}
                  </XStack>
                </YStack>

                {/* Amount. */}
                <YStack gap={8}>
                  <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12} color="#5a6b7b">
                    Amount ({currency})
                  </Text>
                  <XStack
                    alignItems="center"
                    gap={8}
                    borderWidth={1.5}
                    borderColor="rgba(1,46,84,0.08)"
                    borderRadius={16}
                    paddingHorizontal={14}
                    height={54}
                    backgroundColor="#e9eff6"
                  >
                    <Text fontFamily="PlusJakartaSans-Bold" fontSize={15} color="#94a2b1">
                      {currency}
                    </Text>
                    <View width={1} height={22} backgroundColor="rgba(1,46,84,0.10)" />
                    <TextInput
                      value={amount}
                      onChangeText={handleAmount}
                      keyboardType="decimal-pad"
                      placeholder="0.00"
                      placeholderTextColor="#9aa7b5"
                      style={{
                        flex: 1,
                        paddingVertical: 8,
                        fontSize: 15,
                        fontFamily: 'PlusJakartaSans-Medium',
                        color: '#0c1b2a',
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
                            backgroundColor={selected ? '#00508F' : '#eef3fb'}
                          >
                            <Text
                              fontFamily="PlusJakartaSans-Bold"
                              fontSize={12}
                              color={selected ? '#ffffff' : '#00508F'}
                            >
                              {currency} {n}
                            </Text>
                          </View>
                        </Pressable>
                      );
                    })}
                  </XStack>
                </YStack>

                {/* Inline outcome panel — success / processing / error. */}
                {outcome ? <OutcomePanel outcome={outcome} currency={currency} /> : null}

                <ClayButton
                  onPress={onBuy}
                  disabled={!canBuy}
                  loading={busy}
                  accessibilityLabel="Buy airtime"
                >
                  {busy
                    ? 'Processing…'
                    : parsed > 0
                      ? `Buy ${currency} ${parsed.toFixed(2)} airtime`
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

/**
 * Inline result panel rendered under the form after a buy.
 *
 * Success → green confirmation with the number + amount. Processing → neutral
 * "still processing" note carrying the provider/transaction reference so the
 * user has something to quote. Error → red callout with the mapped reason.
 */
function OutcomePanel({ outcome, currency }: { outcome: NonNullable<Outcome>; currency: string }) {
  if (outcome.kind === 'success') {
    const { msisdn, amount } = outcome.result;
    return (
      <ClaySurface depth="soft" radius={16} padding={14}>
        <XStack gap={11} alignItems="flex-start">
          <Ionicons name="checkmark-circle" size={22} color="#0a8a5f" />
          <YStack flex={1} gap={2}>
            <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color="#0a8a5f">
              Airtime sent
            </Text>
            <Text fontFamily="PlusJakartaSans-Medium" fontSize={12.5} color="#3a4756" lineHeight={18}>
              {currency} {parseFloat(amount).toFixed(2)} of airtime is on its way to{' '}
              {maskPhone(msisdn)}.
            </Text>
          </YStack>
        </XStack>
      </ClaySurface>
    );
  }

  if (outcome.kind === 'processing') {
    const ref = outcome.result.provider_reference || outcome.result.transaction_id.slice(0, 8).toUpperCase();
    return (
      <ClaySurface depth="soft" radius={16} padding={14}>
        <XStack gap={11} alignItems="flex-start">
          <Ionicons name="time-outline" size={22} color="#c98a00" />
          <YStack flex={1} gap={2}>
            <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color="#c98a00">
              Processing
            </Text>
            <Text fontFamily="PlusJakartaSans-Medium" fontSize={12.5} color="#3a4756" lineHeight={18}>
              Your top-up is being confirmed. Reference {ref}. We'll update your wallet once it
              completes.
            </Text>
          </YStack>
        </XStack>
      </ClaySurface>
    );
  }

  return (
    <XStack
      backgroundColor="#fdf0ee"
      borderColor="#f6d5cf"
      borderWidth={1}
      borderRadius={16}
      padding={14}
      gap={11}
      alignItems="flex-start"
    >
      <Ionicons name="warning" size={20} color="#c0392b" />
      <YStack flex={1}>
        <Text fontFamily="PlusJakartaSans-Bold" fontSize={13} color="#a52e22">
          Couldn't buy airtime
        </Text>
        <Text
          fontFamily="PlusJakartaSans-Medium"
          fontSize={12}
          color="#8a5a54"
          marginTop={3}
          lineHeight={18}
        >
          {outcome.message}
        </Text>
      </YStack>
    </XStack>
  );
}
