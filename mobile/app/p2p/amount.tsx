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
import { ActivityIndicator, Pressable } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { StepIndicator } from '@/components/brand/StepIndicator';
import { NumericKeypad } from '@/components/forms/NumericKeypad';
import { ApiError, RateLimited, StepUpRequired } from '@/lib/api/errors';
import { newP2PIdempotencyKey, sendP2P } from '@/lib/api/payments';
import { quoteServiceFee } from '@/lib/api/pricing';
import { getMyWallet } from '@/lib/api/wallet';
import { qk } from '@/lib/query';
import { maskPhone } from '@/lib/format';

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
  const qc = useQueryClient();
  const params = useLocalSearchParams<{ phone: string }>();
  const recipientPhone = typeof params.phone === 'string' ? params.phone : '';
  const [amount, setAmount] = useState('');
  const [busy, setBusy] = useState(false);
  const { data } = useQuery({ queryKey: qk.wallet(), queryFn: getMyWallet });

  const zar = data?.accounts.find(
    (a) => a.currency === 'ZAR' && a.account_type === 'financial_wallet',
  );
  const available = parseFloat(zar?.available_balance ?? '0');
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

  // Overdraft must account for the fee — the wallet is debited amount + fee.
  const overdrawn = total > available;
  const canContinue = parsed > 0 && !overdrawn && !busy;
  const display = splitAmount(amount);

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
      const res = await sendP2P({
        recipientPhone,
        amount: amountStr,
        idempotencyKey,
      });
      // Below step-up threshold → backend let it through without a PIN.
      await qc.invalidateQueries({ queryKey: qk.wallet() });
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
        // Above threshold — route to PIN screen, carry the key forward.
        router.push({
          pathname: '/p2p/pin' as never,
          params: {
            phone: recipientPhone,
            amount: amountStr,
            idem: idempotencyKey,
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
      // Cap cents at 2 digits.
      if (dotAt !== -1 && a.length - dotAt - 1 >= 2) return a;
      // Cap whole digits at 7 (R 9,999,999.99).
      if (dotAt === -1 && a.length >= 7) return a;
      return a + key;
    });
  }

  return (
    <View flex={1} backgroundColor="#f4f7fa">
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          <GradientHeader paddingBottom={22}>
            <HeaderBack title="Enter amount" />
            <StepIndicator step={2} caption="Step 2 of 3 · How much are you sending?" />
          </GradientHeader>

          {/* Recipient pill — overlaps the header slightly. */}
          <XStack
            marginHorizontal={18}
            marginTop={16}
            alignItems="center"
            gap={11}
            backgroundColor="#ffffff"
            borderRadius={14}
            padding={11}
            shadowColor="#0c1b2a"
            shadowOpacity={0.05}
            shadowRadius={16}
            shadowOffset={{ width: 0, height: 6 }}
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
              <Text fontFamily="PlusJakartaSans-Bold" fontSize={13.5} color="#0c1b2a">
                {maskPhone(recipientPhone)}
              </Text>
              <Text fontFamily="PlusJakartaSans-Medium" fontSize={11.5} color="#8a98a6">
                Sasai user
              </Text>
            </YStack>
            <View
              backgroundColor="#e7f6ee"
              paddingHorizontal={9}
              paddingVertical={4}
              borderRadius={20}
            >
              <Text fontFamily="PlusJakartaSans-Bold" fontSize={11.5} color="#1aa06b">
                Verified
              </Text>
            </View>
          </XStack>

          {/* Big amount display + balance hint + chips. */}
          <YStack flex={1} alignItems="center" justifyContent="center" paddingHorizontal={22}>
            <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#8a98a6">
              ZAR wallet · R {available.toFixed(2)} available
            </Text>
            <XStack alignItems="flex-start" gap={4} marginTop={10}>
              <Text
                fontFamily="PlusJakartaSans-Bold"
                fontSize={26}
                color="#94a2b1"
                marginTop={8}
              >
                R
              </Text>
              <Text
                fontFamily="PlusJakartaSans-ExtraBold"
                fontSize={56}
                color="#0c1b2a"
                lineHeight={56}
                letterSpacing={-1}
              >
                {display.whole}
                <Text
                  fontFamily="PlusJakartaSans-ExtraBold"
                  fontSize={56}
                  color="#cfd9e3"
                >
                  {display.cents}
                </Text>
              </Text>
            </XStack>
            <XStack gap={8} marginTop={18} flexWrap="wrap" justifyContent="center">
              {CHIPS.map((n) => {
                const value = n.toFixed(2);
                const selected = amount === value;
                return (
                  <Pressable
                    key={n}
                    onPress={() => setAmount(selected ? '' : value)}
                    accessibilityLabel={`Set amount R ${n}`}
                  >
                    <View
                      paddingHorizontal={14}
                      paddingVertical={7}
                      borderRadius={20}
                      backgroundColor={selected ? '#00508F' : '#e9f1f9'}
                    >
                      <Text
                        fontFamily="PlusJakartaSans-Bold"
                        fontSize={12.5}
                        color={selected ? '#ffffff' : '#00508F'}
                      >
                        R{n}
                      </Text>
                    </View>
                  </Pressable>
                );
              })}
            </XStack>
            <Text fontFamily="PlusJakartaSans-Medium" fontSize={12} color="#8a98a6" marginTop={16}>
              Fee R {fee.toFixed(2)} · You pay{' '}
              <Text fontFamily="PlusJakartaSans-Bold" color="#0c1b2a">
                R {total.toFixed(2)}
              </Text>
            </Text>
            {overdrawn ? (
              <Text
                fontFamily="PlusJakartaSans-Bold"
                color="#c0392b"
                fontSize={12.5}
                marginTop={8}
              >
                That's more than your wallet has right now.
              </Text>
            ) : null}
          </YStack>

          <NumericKeypad onPress={handleKey} />
          <View backgroundColor="#ffffff" paddingHorizontal={18} paddingBottom={18}>
            <Pressable
              onPress={onContinue}
              disabled={!canContinue}
              accessibilityRole="button"
              accessibilityLabel="Continue"
              style={({ pressed }) => ({
                opacity: !canContinue ? 0.5 : pressed ? 0.85 : 1,
              })}
            >
              <View
                height={54}
                borderRadius={14}
                backgroundColor="#00508F"
                alignItems="center"
                justifyContent="center"
                shadowColor="#00508F"
                shadowOpacity={0.28}
                shadowRadius={24}
                shadowOffset={{ width: 0, height: 10 }}
              >
                {busy ? (
                  <ActivityIndicator color="#ffffff" />
                ) : (
                  <Text fontFamily="PlusJakartaSans-Bold" fontSize={16} color="#ffffff">
                    Send R {parsed.toFixed(2)}
                  </Text>
                )}
              </View>
            </Pressable>
          </View>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
