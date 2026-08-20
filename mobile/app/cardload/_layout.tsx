/**
 * /cardload stack layout — the simulated "load wallet from card" flow.
 * Slide-from-bottom for the same modal feel as /cashin and /cashout.
 */
import { Stack } from 'expo-router';

import { useColors } from '@/lib/colors';

/** Card-load (simulated card top-up) flow stack. */
export default function CardLoadLayout() {
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
