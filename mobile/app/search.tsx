/**
 * /search — stub for the Search tab.
 *
 * The mock's third tab is Search; we don't have a search endpoint yet
 * (Phase 2 — it'll search across contacts, bills, merchants, and
 * transaction history). For the demo this is a friendly placeholder.
 */
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, YStack } from 'tamagui';

import { BottomTabBar } from '@/components/ui/BottomTabBar';

/** Placeholder for the Search tab. */
export default function SearchScreen() {
  return (
    <View flex={1} backgroundColor="#e8eef5">
      <SafeAreaView style={{ flex: 1 }} edges={['top', 'bottom']}>
        <YStack flex={1} alignItems="center" justifyContent="center" gap={12} paddingHorizontal={32}>
          <Text fontSize={56}>🔍</Text>
          <Text
            fontFamily="PlusJakartaSans-ExtraBold"
            fontSize={22}
            color="#0c1b2a"
            textAlign="center"
          >
            Search coming soon
          </Text>
          <Text
            fontFamily="PlusJakartaSans-Regular"
            fontSize={14}
            color="#6a7888"
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
