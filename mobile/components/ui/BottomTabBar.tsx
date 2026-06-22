/**
 * BottomTabBar — Sasai Pay's 3-tab navigation bar (Pay · Transactions · Search).
 *
 * Lives at the bottom of any tab screen. Active tab gets the primary navy
 * tint + bolder weight; the others render grayscaled and dim. Search is
 * a stub for now — it routes to /search which renders a "Coming soon".
 *
 * Each tab uses a single emoji as its icon to avoid pulling in an icon
 * library; the design mock uses the same emojis so we're authentic.
 */
import { Pressable } from 'react-native';
import { useRouter } from 'expo-router';
import { Text, View, XStack, YStack } from 'tamagui';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

type TabKey = 'pay' | 'transactions' | 'search';

interface Props {
  active: TabKey;
}

const TABS: ReadonlyArray<{ key: TabKey; icon: string; label: string; href: string }> = [
  { key: 'pay', icon: '💳', label: 'Pay', href: '/home' },
  { key: 'transactions', icon: '📊', label: 'Transactions', href: '/transactions' },
  { key: 'search', icon: '🔍', label: 'Search', href: '/search' },
];

/** Bottom tab bar. Renders the 3 Sasai Pay tabs and routes via expo-router. */
export function BottomTabBar({ active }: Props) {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  return (
    <View
      position="absolute"
      bottom={0}
      left={0}
      right={0}
      backgroundColor="#ffffff"
      borderTopWidth={1}
      borderTopColor="#eceff3"
      shadowColor="#0c1b2a"
      shadowOpacity={0.05}
      shadowRadius={20}
      shadowOffset={{ width: 0, height: -6 }}
      paddingBottom={Math.max(insets.bottom - 4, 12)}
    >
      <XStack height={66} alignItems="center" justifyContent="space-around" paddingHorizontal={18}>
        {TABS.map((tab) => {
          const isActive = tab.key === active;
          return (
            <Pressable
              key={tab.key}
              onPress={() => router.push(tab.href as never)}
              accessibilityRole="button"
              accessibilityLabel={tab.label}
              style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}
            >
              <YStack alignItems="center" gap={5} paddingHorizontal={4}>
                <Text fontSize={21} opacity={isActive ? 1 : 0.45}>
                  {tab.icon}
                </Text>
                <Text
                  fontFamily={
                    isActive ? 'PlusJakartaSans-Bold' : 'PlusJakartaSans-SemiBold'
                  }
                  fontSize={11}
                  color={isActive ? '#00508F' : '#9aa7b5'}
                >
                  {tab.label}
                </Text>
              </YStack>
            </Pressable>
          );
        })}
      </XStack>
    </View>
  );
}
