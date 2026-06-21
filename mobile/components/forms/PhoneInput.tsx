/**
 * PhoneInput — country code picker + national-digits input.
 *
 * Composes E.164 on the fly and reports it via `onChange`. The country
 * default is +27 (ZA) per the demo; the other markets are the diaspora
 * corridors we currently care about. Selection state is purely local —
 * the parent only sees the composed phone string.
 */
import { useMemo, useState } from 'react';
import { Pressable, TextInput } from 'react-native';
import { Text, View, XStack, YStack } from 'tamagui';

/** Country options. Order = display order in the picker. */
const COUNTRIES = [
  { code: 'ZA', dial: '+27', label: 'South Africa' },
  { code: 'IN', dial: '+91', label: 'India' },
  { code: 'GB', dial: '+44', label: 'United Kingdom' },
  { code: 'US', dial: '+1', label: 'United States' },
  { code: 'ZW', dial: '+263', label: 'Zimbabwe' },
] as const;

type Country = (typeof COUNTRIES)[number];

interface Props {
  /** Notified every time the composed E.164 phone changes. */
  onChange: (e164: string) => void;
  /** Initial national-number digits (no dial code). */
  initialNational?: string;
}

/** Country code picker + national-number text field that emits E.164. */
export function PhoneInput({ onChange, initialNational = '' }: Props) {
  const [country, setCountry] = useState<Country>(COUNTRIES[0]);
  const [national, setNational] = useState(initialNational);
  const [pickerOpen, setPickerOpen] = useState(false);

  const composed = useMemo(
    () => `${country.dial}${national.replace(/\D/g, '')}`,
    [country, national],
  );

  function handleNationalChange(next: string) {
    // Strip everything that isn't a digit — the input is numeric only.
    const digits = next.replace(/\D/g, '').slice(0, 12);
    setNational(digits);
    onChange(`${country.dial}${digits}`);
  }

  function handleCountrySelect(c: Country) {
    setCountry(c);
    setPickerOpen(false);
    onChange(`${c.dial}${national.replace(/\D/g, '')}`);
  }

  return (
    <YStack gap="$2" width="100%">
      <Text fontSize={13} color="$muted">
        Phone number
      </Text>
      <XStack
        gap="$2"
        alignItems="center"
        borderWidth={1}
        borderColor="$borderColor"
        borderRadius={12}
        padding="$2"
        backgroundColor="$background"
      >
        <Pressable onPress={() => setPickerOpen((v) => !v)}>
          <XStack
            paddingHorizontal={10}
            paddingVertical={6}
            borderRadius={8}
            backgroundColor="$borderColor"
            alignItems="center"
            gap="$1"
          >
            <Text fontWeight="600" color="$color">
              {country.dial}
            </Text>
            <Text color="$muted" fontSize={12}>
              {country.code}
            </Text>
          </XStack>
        </Pressable>
        <TextInput
          value={national}
          onChangeText={handleNationalChange}
          keyboardType="number-pad"
          placeholder="82 555 0001"
          placeholderTextColor="#9BA4AF"
          style={{
            flex: 1,
            paddingVertical: 8,
            fontSize: 18,
            fontFamily: 'Inter-Medium',
            color: '#0B1726',
          }}
          accessibilityLabel="Phone number"
          maxLength={14}
        />
      </XStack>
      {pickerOpen ? (
        <YStack
          marginTop="$1"
          borderWidth={1}
          borderColor="$borderColor"
          borderRadius={12}
          backgroundColor="$background"
          overflow="hidden"
        >
          {COUNTRIES.map((c) => (
            <Pressable
              key={c.code}
              onPress={() => handleCountrySelect(c)}
              accessibilityRole="button"
            >
              <XStack
                paddingHorizontal="$3"
                paddingVertical="$2"
                gap="$2"
                alignItems="center"
                backgroundColor={c.code === country.code ? '$borderColor' : '$background'}
              >
                <Text fontWeight="600" color="$color" minWidth={48}>
                  {c.dial}
                </Text>
                <Text color="$color">{c.label}</Text>
              </XStack>
            </Pressable>
          ))}
        </YStack>
      ) : null}
      <View />
    </YStack>
  );
}
