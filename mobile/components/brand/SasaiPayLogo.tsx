/**
 * Sasai Pay wordmark — the brand identity for the mobile app.
 *
 * Renders the Sasai logo image with the "pay" suffix in teal next to it.
 * The image and text are vertically aligned at the baseline so the
 * "pay" lands on the same line as the "sasai" wordmark. Used on
 * splash, login, and any place we want the full app brand.
 */
import { Image } from 'react-native';
import { Text, XStack } from 'tamagui';

interface Props {
  /** Width of the "sasai" image in px. "pay" text scales with this. */
  width?: number;
  /**
   * Text variant of "pay":
   *   - "teal" (default) — sits next to a light wordmark on dark/navy bg
   *   - "navy" — for use on light surfaces (rare; usually we keep teal)
   */
  payColor?: 'teal' | 'navy';
}

/** Sasai + teal "pay" wordmark. */
export function SasaiPayLogo({ width = 130, payColor = 'teal' }: Props) {
  // The "pay" suffix scales proportionally with the wordmark width so
  // both line up regardless of size.
  const paySize = Math.round(width * 0.2);
  return (
    <XStack alignItems="flex-end" gap={Math.round(width * 0.04)}>
      <Image
        source={require('../../assets/sasai-logo.png')}
        style={{ width, height: Math.round(width * 0.282), resizeMode: 'contain' }}
        accessibilityLabel="Sasai"
      />
      <Text
        fontFamily="PlusJakartaSans-ExtraBold"
        fontSize={paySize}
        lineHeight={Math.round(paySize * 0.85)}
        color={payColor === 'teal' ? '#50C0D0' : '#00508F'}
        letterSpacing={-0.5}
      >
        pay
      </Text>
    </XStack>
  );
}
