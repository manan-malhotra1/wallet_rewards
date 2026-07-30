/**
 * OtpInput — six numeric boxes with auto-advance + paste-fill + auto-submit.
 *
 * Behaviour:
 *   - Each cell holds exactly one digit; entering a digit advances focus.
 *   - Backspace on an empty cell moves focus back.
 *   - Pasting a 6-digit string fills all boxes at once.
 *   - When all six are filled, `onComplete` fires with the 6-digit string.
 *
 * No native code — uses a hidden TextInput per cell. Works in any RN env.
 */
import { useEffect, useRef, useState } from 'react';
import {
  NativeSyntheticEvent,
  TextInput,
  TextInputKeyPressEventData,
} from 'react-native';
import { XStack, YStack } from 'tamagui';

interface Props {
  /** Fires when all 6 digits are populated. */
  onComplete: (otp: string) => void;
  /** External reset signal — bump to clear all boxes (used on wrong-OTP error). */
  resetSignal?: number;
}

const LENGTH = 6;

/** Six-box OTP entry. Auto-submits when filled. */
export function OtpInput({ onComplete, resetSignal }: Props) {
  const [digits, setDigits] = useState<string[]>(() => Array(LENGTH).fill(''));
  const refs = useRef<Array<TextInput | null>>([]);

  // External reset — clear and refocus the first cell.
  useEffect(() => {
    if (resetSignal === undefined) return;
    setDigits(Array(LENGTH).fill(''));
    refs.current[0]?.focus();
  }, [resetSignal]);

  // Fire onComplete the moment every cell holds a digit.
  useEffect(() => {
    if (digits.every((d) => d.length === 1)) {
      onComplete(digits.join(''));
    }
  }, [digits, onComplete]);

  function handleChange(index: number, raw: string) {
    // Allow paste of multi-digit string into a single cell.
    const onlyDigits = raw.replace(/\D/g, '');
    if (onlyDigits.length > 1) {
      const next = Array(LENGTH).fill('');
      for (let i = 0; i < Math.min(onlyDigits.length, LENGTH); i += 1) {
        next[i] = onlyDigits[i];
      }
      setDigits(next);
      refs.current[Math.min(onlyDigits.length, LENGTH) - 1]?.focus();
      return;
    }
    const next = [...digits];
    next[index] = onlyDigits.slice(0, 1);
    setDigits(next);
    // Advance only when a digit was actually entered.
    if (onlyDigits && index < LENGTH - 1) {
      refs.current[index + 1]?.focus();
    }
  }

  function handleKeyPress(
    index: number,
    e: NativeSyntheticEvent<TextInputKeyPressEventData>,
  ) {
    // Step back on backspace from an empty cell.
    if (e.nativeEvent.key === 'Backspace' && !digits[index] && index > 0) {
      refs.current[index - 1]?.focus();
    }
  }

  return (
    <YStack alignItems="center" width="100%">
      <XStack gap="$2">
        {digits.map((d, i) => (
          <TextInput
            // eslint-disable-next-line react/no-array-index-key
            key={i}
            ref={(el) => {
              refs.current[i] = el;
            }}
            value={d}
            onChangeText={(t) => handleChange(i, t)}
            onKeyPress={(e) => handleKeyPress(i, e)}
            keyboardType="number-pad"
            maxLength={1}
            textContentType="oneTimeCode"
            autoComplete="sms-otp"
            style={{
              width: 46,
              height: 58,
              borderWidth: 1.5,
              borderColor: d ? '#00508F' : 'rgba(1,46,84,0.10)',
              borderRadius: 16,
              textAlign: 'center',
              fontSize: 24,
              fontFamily: 'PlusJakartaSans-SemiBold',
              color: '#0c1b2a',
              backgroundColor: d ? '#f2f6fb' : '#e9eff6',
            }}
            accessibilityLabel={`OTP digit ${i + 1}`}
          />
        ))}
      </XStack>
    </YStack>
  );
}
