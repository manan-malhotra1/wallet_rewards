/**
 * AmountInput — big-number ZAR entry with quick-amount chips.
 *
 * Renders "R" + a numeric TextInput sized for thumb taps. The chip row
 * below offers preset amounts (R 50 / 100 / 200 / 500) — tap fills the
 * value, tap again clears it. Decimal-only input; non-numeric is stripped.
 */
import { useMemo } from 'react';
import { Pressable } from 'react-native';
import { Input, Text, XStack, YStack } from 'tamagui';

interface Props {
  /** Decimal-string amount; "" when empty. */
  value: string;
  onChange: (next: string) => void;
  /** Defaults to [50, 100, 200, 500]. Pass [] to hide the chip row. */
  quickAmounts?: number[];
}

/** Big-number amount input with preset chips. */
export function AmountInput({ value, onChange, quickAmounts }: Props) {
  const chips = useMemo(() => quickAmounts ?? [50, 100, 200, 500], [quickAmounts]);

  function setText(next: string) {
    // Strip anything that isn't a digit or single decimal point.
    const cleaned = next.replace(/[^0-9.]/g, '');
    const firstDot = cleaned.indexOf('.');
    const normalised =
      firstDot === -1
        ? cleaned
        : cleaned.slice(0, firstDot + 1) + cleaned.slice(firstDot + 1).replace(/\./g, '');
    onChange(normalised);
  }

  function setAmount(n: number) {
    const next = n.toFixed(2);
    // Toggle behavior: tap an already-chosen chip to clear.
    onChange(value === next ? '' : next);
  }

  return (
    <YStack gap="$4" alignItems="center">
      <XStack alignItems="baseline" gap="$2">
        <Text fontFamily="Inter-Medium" fontSize={28} color="$muted">
          R
        </Text>
        <Input
          value={value}
          onChangeText={setText}
          placeholder="0.00"
          keyboardType="decimal-pad"
          fontSize={48}
          fontFamily="Inter-Bold"
          color="$ink"
          textAlign="center"
          borderWidth={0}
          backgroundColor="transparent"
          minWidth={180}
          maxLength={10}
        />
      </XStack>
      {chips.length > 0 && (
        <XStack gap="$2" flexWrap="wrap" justifyContent="center">
          {chips.map((n) => {
            const selected = value === n.toFixed(2);
            return (
              <Pressable
                key={n}
                onPress={() => setAmount(n)}
                accessibilityLabel={`Set amount to R ${n}`}
              >
                <YStack
                  paddingHorizontal="$3"
                  paddingVertical="$2"
                  borderRadius={16}
                  backgroundColor={selected ? '$sasaiNavy' : 'rgba(20,73,137,0.08)'}
                >
                  <Text
                    fontFamily="Inter-Medium"
                    color={selected ? 'white' : '$sasaiNavy'}
                  >
                    R {n}
                  </Text>
                </YStack>
              </Pressable>
            );
          })}
        </XStack>
      )}
    </YStack>
  );
}
