/**
 * PhoneInput — country code picker + national-digits input (Sasai Pay redesign).
 *
 * Composes E.164 on the fly and reports it via `onChange`. Default country
 * is +263 Zimbabwe to match the design mock's home market; +27 South
 * Africa is the secondary option for the seeded ZA tenant. Selection state
 * is purely local — the parent only sees the composed phone string.
 */
import { useMemo, useState } from 'react';
import { Pressable, TextInput } from 'react-native';
import { Text, View, XStack, YStack } from 'tamagui';

/** Country options. Order = display order in the picker. */
const COUNTRIES = [
  { code: 'ZW', dial: '+263', label: 'Zimbabwe', flag: '🇿🇼' },
  { code: 'ZA', dial: '+27', label: 'South Africa', flag: '🇿🇦' },
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
        color="#5a6b7b"
      >
        Mobile number
      </Text>
      <XStack
        alignItems="center"
        gap={10}
        borderWidth={1.5}
        borderColor={focused ? '#00508F' : 'rgba(1,46,84,0.08)'}
        borderRadius={16}
        paddingHorizontal={14}
        height={54}
        backgroundColor={focused ? '#f2f6fb' : '#e9eff6'}
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
              color="#0c1b2a"
            >
              {country.dial}
            </Text>
          </XStack>
        </Pressable>
        <View width={1} height={22} backgroundColor="rgba(1,46,84,0.10)" />
        <TextInput
          value={national}
          onChangeText={handleNationalChange}
          keyboardType="number-pad"
          placeholder="77 412 8890"
          placeholderTextColor="#9aa7b5"
          style={{
            flex: 1,
            paddingVertical: 8,
            fontSize: 15,
            fontFamily: 'PlusJakartaSans-Medium',
            color: '#0c1b2a',
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
          backgroundColor="#f2f6fb"
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
                  c.code === country.code ? '#e3ecf5' : 'transparent'
                }
              >
                <Text fontSize={18}>{c.flag}</Text>
                <Text
                  fontFamily="PlusJakartaSans-Bold"
                  fontSize={14}
                  color="#0c1b2a"
                  minWidth={48}
                >
                  {c.dial}
                </Text>
                <Text
                  fontFamily="PlusJakartaSans-Medium"
                  fontSize={14}
                  color="#0c1b2a"
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
