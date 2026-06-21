/**
 * PinInput — pip display + custom numeric keypad (no native keyboard).
 *
 * 4-digit PIN entry. The native keyboard is intentionally suppressed so
 * the user sees only the keypad we render — eliminates the chance of a
 * malicious IME logging the PIN on Android, and gives us a consistent
 * tap target across platforms.
 *
 * The parent controls submission timing — we call `onChange` on each digit
 * and `onComplete` once 4 digits are entered.
 */
import { Pressable } from 'react-native';
import { Text, View, XStack, YStack } from 'tamagui';

interface Props {
  value: string;
  onChange: (next: string) => void;
  /** Fires when 4 digits have been entered (does NOT clear; parent decides). */
  onComplete?: (pin: string) => void;
  length?: number;
  /** Optional helper text rendered above the pips (e.g. "Enter PIN"). */
  label?: string;
  /** Renders pips in error tint to signal a failed attempt. */
  errored?: boolean;
}

const KEYS: Array<'0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | 'back'> = [
  '1', '2', '3',
  '4', '5', '6',
  '7', '8', '9',
  // Empty slot, 0, backspace — matches every PIN pad on earth.
  '0', 'back',
];

/** Pip-display PIN entry with a built-in numeric keypad. */
export function PinInput({
  value,
  onChange,
  onComplete,
  length = 4,
  label,
  errored = false,
}: Props) {
  function press(key: (typeof KEYS)[number]) {
    if (key === 'back') {
      if (value.length === 0) return;
      onChange(value.slice(0, -1));
      return;
    }
    if (value.length >= length) return;
    const next = value + key;
    onChange(next);
    if (next.length === length && onComplete) onComplete(next);
  }

  return (
    <YStack alignItems="center" width="100%" gap="$4">
      {label ? (
        <Text fontSize={14} color="$muted">
          {label}
        </Text>
      ) : null}
      <XStack gap="$3">
        {Array.from({ length }).map((_, i) => {
          const filled = i < value.length;
          return (
            <View
              // eslint-disable-next-line react/no-array-index-key
              key={i}
              width={16}
              height={16}
              borderRadius={8}
              backgroundColor={
                errored
                  ? '#EF4444'
                  : filled
                    ? '#144989'
                    : '#E5EAF0'
              }
            />
          );
        })}
      </XStack>
      <YStack gap="$2" width={264}>
        {[
          ['1', '2', '3'],
          ['4', '5', '6'],
          ['7', '8', '9'],
          ['', '0', 'back'],
        ].map((row, ri) => (
          <XStack
            // eslint-disable-next-line react/no-array-index-key
            key={ri}
            gap="$2"
            justifyContent="space-between"
          >
            {row.map((k, ci) => (
              <Pressable
                // eslint-disable-next-line react/no-array-index-key
                key={ci}
                onPress={() => {
                  if (k === '') return;
                  press(k as (typeof KEYS)[number]);
                }}
                disabled={k === ''}
                accessibilityRole="button"
                accessibilityLabel={
                  k === 'back' ? 'Delete' : k === '' ? 'empty' : `Digit ${k}`
                }
              >
                <View
                  width={80}
                  height={56}
                  borderRadius={12}
                  alignItems="center"
                  justifyContent="center"
                  backgroundColor={k === '' ? 'transparent' : '#F4F6F9'}
                >
                  <Text
                    fontSize={k === 'back' ? 18 : 22}
                    fontWeight="600"
                    color="$ink"
                  >
                    {k === 'back' ? '←' : k}
                  </Text>
                </View>
              </Pressable>
            ))}
          </XStack>
        ))}
      </YStack>
    </YStack>
  );
}
