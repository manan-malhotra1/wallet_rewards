/**
 * NumericKeypad — the white-background pad shown at the bottom of the
 * amount screen. Supports a decimal "." key and a backspace, and emits
 * structured events so the parent owns the actual amount-string state
 * (allowing it to enforce max digits, decimal places, etc.).
 */
import { Pressable } from 'react-native';
import { Text, View, XStack, YStack } from 'tamagui';

interface Props {
  /** Fires with one of: '0'..'9', '.', 'back'. */
  onPress: (key: '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '.' | 'back') => void;
  /** Hide the "." key (for screens that only take whole numbers). */
  decimalsAllowed?: boolean;
}

const ROWS: ReadonlyArray<ReadonlyArray<'0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '.' | 'back'>> = [
  ['1', '2', '3'],
  ['4', '5', '6'],
  ['7', '8', '9'],
  ['.', '0', 'back'],
];

/** White numeric keypad with optional decimal point and a backspace. */
export function NumericKeypad({ onPress, decimalsAllowed = true }: Props) {
  return (
    <YStack backgroundColor="#ffffff" paddingHorizontal={22} paddingTop={8} paddingBottom={4}>
      {ROWS.map((row, ri) => (
        <XStack
          // eslint-disable-next-line react/no-array-index-key
          key={ri}
          gap={2}
        >
          {row.map((k) => {
            const isBack = k === 'back';
            const isDot = k === '.';
            const hidden = isDot && !decimalsAllowed;
            return (
              <Pressable
                key={k}
                onPress={hidden ? undefined : () => onPress(k)}
                disabled={hidden}
                accessibilityRole="button"
                accessibilityLabel={isBack ? 'Delete' : `Key ${k}`}
                style={({ pressed }) => ({
                  flex: 1,
                  opacity: hidden ? 0 : pressed ? 0.5 : 1,
                })}
              >
                <View height={48} alignItems="center" justifyContent="center">
                  <Text
                    fontFamily="PlusJakartaSans-SemiBold"
                    fontSize={isBack ? 22 : 24}
                    color={isBack ? '#8a98a6' : '#0c1b2a'}
                  >
                    {isBack ? '⌫' : k}
                  </Text>
                </View>
              </Pressable>
            );
          })}
        </XStack>
      ))}
    </YStack>
  );
}
