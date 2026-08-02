/**
 * CurrencySelector — in-flow wallet currency switcher for the send / cash-out
 * amount screens.
 *
 * Replaces the static "{currency} wallet · {balance} available" hint. When the
 * user holds more than one financial wallet it renders a centered row of clay
 * currency chips (active highlighted) plus the selected wallet's available
 * balance; tapping a chip switches the active wallet so the balance, symbol,
 * fee/total preview, and overdraft check all re-evaluate against it. With a
 * single wallet it degrades to the original static label (no selector).
 */
import { Pressable } from 'react-native';
import { Text, View, XStack } from 'tamagui';

import { useColors } from '@/lib/colors';
import { formatMoney } from '@/lib/format';

interface CurrencySelectorProps {
  /** The user's financial-wallet currency codes (e.g. ['ZAR', 'INR']). */
  currencies: string[];
  /** Currently selected currency code. */
  selected: string;
  /** Called with the tapped currency code when the user switches wallet. */
  onSelect: (currency: string) => void;
  /** Available balance (numeric) of the selected wallet, for the hint line. */
  available: number;
}

/** Wallet currency switcher; static label when only one wallet exists. */
export function CurrencySelector({
  currencies,
  selected,
  onSelect,
  available,
}: CurrencySelectorProps) {
  const colors = useColors();
  const availableText = `${formatMoney(available, selected)} available`;

  // Single wallet → no choice to make; keep the original muted hint line.
  if (currencies.length <= 1) {
    return (
      <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color={colors.textMuted}>
        {selected} wallet · {availableText}
      </Text>
    );
  }

  return (
    <XStack alignItems="center" gap={6} flexWrap="wrap" justifyContent="center">
      {currencies.map((c) => {
        const active = c === selected;
        return (
          <Pressable
            key={c}
            onPress={() => onSelect(c)}
            accessibilityRole="button"
            accessibilityLabel={`Pay from ${c} wallet`}
            accessibilityState={{ selected: active }}
          >
            <View
              paddingHorizontal={13}
              paddingVertical={6}
              borderRadius={20}
              backgroundColor={active ? colors.navy : colors.rim}
            >
              <Text
                fontFamily="PlusJakartaSans-Bold"
                fontSize={12}
                color={active ? colors.textOnDark : colors.navy}
              >
                {c}
              </Text>
            </View>
          </Pressable>
        );
      })}
      <Text
        fontFamily="PlusJakartaSans-SemiBold"
        fontSize={12.5}
        color={colors.textMuted}
        marginLeft={2}
      >
        · {availableText}
      </Text>
    </XStack>
  );
}
