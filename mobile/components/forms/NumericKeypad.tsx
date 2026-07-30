/**
 * NumericKeypad — the white-background pad shown at the bottom of the
 * amount screen. Supports a decimal "." key and a backspace, and emits
 * structured events so the parent owns the actual amount-string state
 * (allowing it to enforce max digits, decimal places, etc.).
 */
import { Text, XStack, YStack } from 'tamagui';

import { ClayKey, clay } from '@/components/clay';

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

/** Clay numeric keypad with optional decimal point and a backspace. */
export function NumericKeypad({ onPress, decimalsAllowed = true }: Props) {
  return (
    <YStack
      backgroundColor={clay.claySurface.bg}
      paddingHorizontal={18}
      paddingTop={10}
      paddingBottom={6}
      gap={10}
    >
      {ROWS.map((row, ri) => (
        <XStack
          // eslint-disable-next-line react/no-array-index-key
          key={ri}
          gap={10}
        >
          {row.map((k) => {
            const isBack = k === 'back';
            const isDot = k === '.';
            const hidden = isDot && !decimalsAllowed;
            return (
              <ClayKey
                key={k}
                flex
                height={52}
                hidden={hidden}
                onPress={() => onPress(k)}
                accessibilityLabel={isBack ? 'Delete' : `Key ${k}`}
              >
                <Text
                  fontFamily="PlusJakartaSans-SemiBold"
                  fontSize={isBack ? 22 : 24}
                  color={isBack ? '#5a6b7b' : '#0c1b2a'}
                >
                  {isBack ? '⌫' : k}
                </Text>
              </ClayKey>
            );
          })}
        </XStack>
      ))}
    </YStack>
  );
}
