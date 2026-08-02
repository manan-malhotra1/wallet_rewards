/**
 * HeaderBack — the back-arrow chip + title row used inside GradientHeader
 * on every non-home screen (transactions detail, rewards, P2P, etc.).
 *
 * The chip is a 34×34 translucent square with a "‹" glyph; title is the
 * white ExtraBold heading next to it. Tapping the chip pops the route.
 */
import { Pressable } from 'react-native';
import { useRouter } from 'expo-router';
import { Text, View, XStack } from 'tamagui';

import { useColors } from '@/lib/colors';

interface Props {
  title: string;
  /** Override what the back button does. Defaults to router.back(). */
  onBack?: () => void;
}

/** Back chip + screen title row for gradient-header screens. */
export function HeaderBack({ title, onBack }: Props) {
  const colors = useColors();
  const router = useRouter();
  function handleBack() {
    if (onBack) return onBack();
    if (router.canGoBack()) router.back();
  }
  return (
    <XStack alignItems="center" gap={12} marginTop={16}>
      <Pressable
        onPress={handleBack}
        accessibilityRole="button"
        accessibilityLabel="Back"
        style={({ pressed }) => ({ opacity: pressed ? 0.6 : 1 })}
      >
        <View
          width={34}
          height={34}
          borderRadius={11}
          backgroundColor="rgba(255,255,255,0.14)"
          alignItems="center"
          justifyContent="center"
        >
          <Text fontSize={18} color={colors.textOnDark}>
            ‹
          </Text>
        </View>
      </Pressable>
      <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={18} color={colors.textOnDark}>
        {title}
      </Text>
    </XStack>
  );
}
