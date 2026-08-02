/**
 * /p2p stack layout — slide-from-bottom animation gives the flow a modal feel
 * even though it's a regular stack (no native modal presentation chrome).
 */
import { Stack } from 'expo-router';

import { useColors } from '@/lib/colors';

/** Send-money flow stack. */
export default function P2PLayout() {
  const colors = useColors();
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        animation: 'slide_from_bottom',
        contentStyle: { backgroundColor: colors.screenBg },
      }}
    />
  );
}
