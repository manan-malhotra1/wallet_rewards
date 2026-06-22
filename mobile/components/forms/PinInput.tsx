/**
 * PinInput — pip display + custom numeric keypad (Sasai Pay redesign).
 *
 * 4-digit PIN entry. The native keyboard is intentionally suppressed so
 * the user sees only the keypad we render — eliminates the chance of a
 * malicious IME logging the PIN on Android, and gives us a consistent
 * tap target across platforms.
 *
 * The parent controls submission timing — we call `onChange` on each digit
 * and `onComplete` once `length` digits are entered.
 */
import { Pressable } from 'react-native';
import { Text, View, XStack, YStack } from 'tamagui';

interface Props {
  value: string;
  onChange: (next: string) => void;
  /** Fires once `length` digits are entered. Parent decides whether to clear. */
  onComplete?: (pin: string) => void;
  length?: number;
  /** Optional small helper text above the pips ("Enter your PIN to authorise"). */
  label?: string;
  /** Renders pips in error tint to signal a failed attempt. */
  errored?: boolean;
  /** Color tint for filled pips. Defaults to Sasai primary navy. */
  pipColor?: string;
  /** Side icon on the bottom-left of the keypad (e.g., biometric ⌁). */
  bottomLeftIcon?: string;
  /** Called when the side icon is pressed. */
  onBottomLeftPress?: () => void;
}

const ROWS: ReadonlyArray<ReadonlyArray<'0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | 'back' | 'side'>> = [
  ['1', '2', '3'],
  ['4', '5', '6'],
  ['7', '8', '9'],
  ['side', '0', 'back'],
];

/** Pip-display PIN entry with a built-in numeric keypad. */
export function PinInput({
  value,
  onChange,
  onComplete,
  length = 4,
  label,
  errored = false,
  pipColor = '#00508F',
  bottomLeftIcon,
  onBottomLeftPress,
}: Props) {
  function press(key: '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | 'back') {
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
    <YStack alignItems="center" width="100%" gap={22}>
      {label ? (
        <Text
          fontFamily="PlusJakartaSans-Bold"
          fontSize={14}
          color="#0c1b2a"
        >
          {label}
        </Text>
      ) : null}
      <XStack gap={18}>
        {Array.from({ length }).map((_, i) => {
          const filled = i < value.length;
          return (
            <View
              // eslint-disable-next-line react/no-array-index-key
              key={i}
              width={14}
              height={14}
              borderRadius={7}
              backgroundColor={errored ? '#c0392b' : filled ? pipColor : '#cfd9e3'}
            />
          );
        })}
      </XStack>
      <YStack gap={2} width="100%" maxWidth={300} alignSelf="center">
        {ROWS.map((row, ri) => (
          <XStack
            // eslint-disable-next-line react/no-array-index-key
            key={ri}
            justifyContent="space-around"
            gap={2}
          >
            {row.map((k, ci) => {
              const isSide = k === 'side';
              const isBack = k === 'back';
              const label = isSide
                ? bottomLeftIcon ?? ''
                : isBack
                  ? '⌫'
                  : k;
              const onPress = isSide
                ? onBottomLeftPress
                : isBack || !isSide
                  ? () => press(k as 'back' | '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9')
                  : undefined;
              const dim = isSide && !bottomLeftIcon;
              return (
                <Pressable
                  // eslint-disable-next-line react/no-array-index-key
                  key={ci}
                  onPress={dim ? undefined : onPress}
                  disabled={dim}
                  accessibilityRole="button"
                  accessibilityLabel={
                    isBack
                      ? 'Delete'
                      : isSide
                        ? (bottomLeftIcon ? 'Biometric login' : 'empty')
                        : `Digit ${k}`
                  }
                  style={({ pressed }) => ({
                    flex: 1,
                    opacity: pressed && !dim ? 0.55 : 1,
                  })}
                >
                  <View
                    height={56}
                    alignItems="center"
                    justifyContent="center"
                  >
                    <Text
                      fontFamily={
                        isBack || isSide ? 'PlusJakartaSans-Medium' : 'PlusJakartaSans-SemiBold'
                      }
                      fontSize={isBack || isSide ? 22 : 26}
                      color={isSide || isBack ? '#8a98a6' : '#0c1b2a'}
                    >
                      {label}
                    </Text>
                  </View>
                </Pressable>
              );
            })}
          </XStack>
        ))}
      </YStack>
    </YStack>
  );
}
