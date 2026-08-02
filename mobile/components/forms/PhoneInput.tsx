/**
 * PhoneInput — country code picker + national-digits input (Sasai Pay redesign).
 *
 * Composes E.164 on the fly and reports it via `onChange`. Default country
 * is +27 South Africa (the primary seeded tenant market), so login and
 * recipient entry start on +27; other markets are one tap away in the
 * picker. Selection state is purely local — the parent only sees the
 * composed phone string.
 */
import { useMemo, useState } from 'react';
import { Pressable, TextInput } from 'react-native';
import { Text, View, XStack, YStack } from 'tamagui';

import { useColors } from '@/lib/colors';

/**
 * Country options. Order = display order in the picker, and the first
 * entry is the default selection — South Africa (+27) leads so the input
 * starts on the primary seeded market.
 */
const COUNTRIES = [
  { code: 'ZA', dial: '+27', label: 'South Africa', flag: '🇿🇦' },
  { code: 'ZW', dial: '+263', label: 'Zimbabwe', flag: '🇿🇼' },
  { code: 'IN', dial: '+91', label: 'India', flag: '🇮🇳' },
  { code: 'GB', dial: '+44', label: 'United Kingdom', flag: '🇬🇧' },
  { code: 'US', dial: '+1', label: 'United States', flag: '🇺🇸' },
] as const;

type Country = (typeof COUNTRIES)[number];

interface Props {
  /** Notified every time the composed E.164 phone changes. */
  onChange: (e164: string) => void;
  /** Initial national-number digits (no dial code). */
  initialNational?: string;
  /**
   * Visual variant.
   *   - `default` — soft input fill, used on the phone-entry screen.
   *   - `focused` — primary-colored border, lifts off the surface, used on
   *     P2P recipient (the field is the focus of the screen).
   */
  variant?: 'default' | 'focused';
}

/** Country code picker + national-number input that emits E.164. */
export function PhoneInput({
  onChange,
  initialNational = '',
  variant = 'default',
}: Props) {
  const colors = useColors();
  const [country, setCountry] = useState<Country>(COUNTRIES[0]);
  const [national, setNational] = useState(initialNational);
  const [pickerOpen, setPickerOpen] = useState(false);

  const composed = useMemo(
    () => `${country.dial}${national.replace(/\D/g, '')}`,
    [country, national],
  );
  // composed is for memoization side-effects in dev (Hermes only logs onChange).
  void composed;

  function handleNationalChange(next: string) {
    const digits = next.replace(/\D/g, '').slice(0, 12);
    setNational(digits);
    onChange(`${country.dial}${digits}`);
  }

  function handleCountrySelect(c: Country) {
    setCountry(c);
    setPickerOpen(false);
    onChange(`${c.dial}${national.replace(/\D/g, '')}`);
  }

  const focused = variant === 'focused';

  return (
    <YStack gap="$2" width="100%">
      <Text
        fontFamily="PlusJakartaSans-SemiBold"
        fontSize={12}
        color={colors.textMuted}
      >
        Mobile number
      </Text>
      <XStack
        alignItems="center"
        gap={10}
        borderWidth={1.5}
        borderColor={focused ? colors.navy : colors.hairline}
        borderRadius={16}
        paddingHorizontal={14}
        height={54}
        backgroundColor={focused ? colors.clayRaised : colors.clayInset}
        shadowColor={focused ? '#012e54' : 'transparent'}
        shadowOpacity={focused ? 0.16 : 0}
        shadowRadius={focused ? 18 : 0}
        shadowOffset={{ width: 0, height: 10 }}
        style={{ elevation: focused ? 6 : 0 }}
      >
        <Pressable
          onPress={() => setPickerOpen((v) => !v)}
          accessibilityRole="button"
          accessibilityLabel={`Country code ${country.dial}`}
        >
          <XStack alignItems="center" gap={6}>
            <Text fontSize={18}>{country.flag}</Text>
            <Text
              fontFamily="PlusJakartaSans-Bold"
              fontSize={15}
              color={colors.text}
            >
              {country.dial}
            </Text>
          </XStack>
        </Pressable>
        <View width={1} height={22} backgroundColor={colors.hairline} />
        <TextInput
          value={national}
          onChangeText={handleNationalChange}
          keyboardType="number-pad"
          placeholder="77 412 8890"
          placeholderTextColor={colors.textFaint}
          style={{
            flex: 1,
            paddingVertical: 8,
            fontSize: 15,
            fontFamily: 'PlusJakartaSans-Medium',
            color: colors.text,
          }}
          accessibilityLabel="Phone number"
          maxLength={14}
        />
      </XStack>
      {pickerOpen ? (
        <YStack
          marginTop={6}
          borderWidth={1}
          borderColor="rgba(255,255,255,0.85)"
          borderRadius={18}
          backgroundColor={colors.clayRaised}
          overflow="hidden"
          shadowColor="#012e54"
          shadowOpacity={0.16}
          shadowRadius={22}
          shadowOffset={{ width: 0, height: 10 }}
          style={{ elevation: 8 }}
        >
          {COUNTRIES.map((c) => (
            <Pressable
              key={c.code}
              onPress={() => handleCountrySelect(c)}
              accessibilityRole="button"
            >
              <XStack
                paddingHorizontal={14}
                paddingVertical={12}
                gap={10}
                alignItems="center"
                backgroundColor={
                  c.code === country.code ? colors.clayInset : 'transparent'
                }
              >
                <Text fontSize={18}>{c.flag}</Text>
                <Text
                  fontFamily="PlusJakartaSans-Bold"
                  fontSize={14}
                  color={colors.text}
                  minWidth={48}
                >
                  {c.dial}
                </Text>
                <Text
                  fontFamily="PlusJakartaSans-Medium"
                  fontSize={14}
                  color={colors.text}
                >
                  {c.label}
                </Text>
              </XStack>
            </Pressable>
          ))}
        </YStack>
      ) : null}
    </YStack>
  );
}
