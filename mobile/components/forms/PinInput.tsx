/**
 * PinInput — pip display + custom numeric keypad (Sasai Pay redesign).
 *
 * 4-digit PIN entry. The native keyboard is intentionally suppressed so
 * the user sees only the keypad we render — eliminates the chance of a
 * malicious IME logging the PIN on Android, and gives us a consistent
 * tap target across platforms.
 *
 * The parent controls submission timing — we call `onChange` on each
 * digit and `onComplete` once `length` digits are entered.
 *
 * The keypad uses explicit pixel widths instead of flex:1 + width:'100%'.
 * Inside an Animated.View (which has no intrinsic width) the percentage
 * widths collapse to 0 on iOS — the keypad would render at zero height
 * with no visible buttons.
 */
import { StyleSheet, View } from 'react-native';
import { Text, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { ClayKey } from '@/components/clay';

interface Props {
  value: string;
  onChange: (next: string) => void;
  /** Fires once `length` digits are entered. Parent decides whether to clear. */
  onComplete?: (pin: string) => void;
  length?: number;
  /** Optional small helper text above the pips. */
  label?: string;
  /** Renders pips in error tint to signal a failed attempt. */
  errored?: boolean;
  /** Color tint for filled pips. Defaults to Sasai primary navy. */
  pipColor?: string;
  /** Side icon on the bottom-left of the keypad (e.g., biometric). */
  bottomLeftIcon?: string;
  /** Called when the side icon is pressed. */
  onBottomLeftPress?: () => void;
}

type KeypadKey =
  | '0' | '1' | '2' | '3' | '4'
  | '5' | '6' | '7' | '8' | '9'
  | 'back' | 'side';

const ROWS: ReadonlyArray<ReadonlyArray<KeypadKey>> = [
  ['1', '2', '3'],
  ['4', '5', '6'],
  ['7', '8', '9'],
  ['side', '0', 'back'],
];

const KEY_WIDTH = 80;
const KEY_HEIGHT = 56;
const KEY_GAP = 10;
const KEYPAD_WIDTH = KEY_WIDTH * 3 + KEY_GAP * 2;

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
  function press(key: Exclude<KeypadKey, 'side'>) {
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
    <YStack alignItems="center" gap={22}>
      {label ? (
        <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#0c1b2a">
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
              style={{
                width: 14,
                height: 14,
                borderRadius: 7,
                backgroundColor: errored
                  ? '#c0392b'
                  : filled
                    ? pipColor
                    : '#cfd9e3',
              }}
            />
          );
        })}
      </XStack>
      <View style={{ width: KEYPAD_WIDTH }}>
        {ROWS.map((row, ri) => (
          <View
            // eslint-disable-next-line react/no-array-index-key
            key={ri}
            style={[styles.row, ri < ROWS.length - 1 && { marginBottom: KEY_GAP }]}
          >
            {row.map((k, ci) => {
              const isSide = k === 'side';
              const isBack = k === 'back';
              const dim = isSide && !bottomLeftIcon;
              const label = isSide ? bottomLeftIcon ?? '' : k;
              const handlePress = isSide
                ? onBottomLeftPress
                : () => press(k as Exclude<KeypadKey, 'side'>);
              return (
                <View
                  // eslint-disable-next-line react/no-array-index-key
                  key={ci}
                  style={ci < row.length - 1 ? { marginRight: KEY_GAP } : undefined}
                >
                  <ClayKey
                    width={KEY_WIDTH}
                    height={KEY_HEIGHT}
                    hidden={dim}
                    onPress={handlePress}
                    accessibilityLabel={
                      isBack
                        ? 'Delete'
                        : isSide
                          ? bottomLeftIcon
                            ? 'Biometric login'
                            : 'empty'
                          : `Digit ${k}`
                    }
                  >
                    {isBack ? (
                      <Ionicons name="backspace-outline" size={24} color="#5a6b7b" />
                    ) : (
                      <Text
                        fontFamily={
                          isSide
                            ? 'PlusJakartaSans-Medium'
                            : 'PlusJakartaSans-SemiBold'
                        }
                        fontSize={isSide ? 22 : 26}
                        color={isSide ? '#5a6b7b' : '#0c1b2a'}
                      >
                        {label}
                      </Text>
                    )}
                  </ClayKey>
                </View>
              );
            })}
          </View>
        ))}
      </View>
    </YStack>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-start',
  },
});
