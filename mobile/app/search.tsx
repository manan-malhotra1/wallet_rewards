/**
 * /search — stub for the Search tab.
 *
 * The mock's third tab is Search; we don't have a search endpoint yet
 * (Phase 2 — it'll search across contacts, bills, merchants, and
 * transaction history). For the demo this is a friendly placeholder.
 */
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { BottomTabBar } from '@/components/ui/BottomTabBar';
import { useColors } from '@/lib/colors';

/** Placeholder for the Search tab. */
export default function SearchScreen() {
  const colors = useColors();
  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['top', 'bottom']}>
        <YStack flex={1} alignItems="center" justifyContent="center" gap={12} paddingHorizontal={32}>
          <Ionicons name="search" size={56} color={colors.navy} />
          <Text
            fontFamily="PlusJakartaSans-ExtraBold"
            fontSize={22}
            color={colors.text}
            textAlign="center"
          >
            Search coming soon
          </Text>
          <Text
            fontFamily="PlusJakartaSans-Regular"
            fontSize={14}
            color={colors.textMuted}
            textAlign="center"
          >
            Find a contact, a bill, a merchant, or any past payment in
            one place.
          </Text>
        </YStack>
      </SafeAreaView>
      <BottomTabBar active="search" />
    </View>
  );
}
