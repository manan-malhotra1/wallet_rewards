/**
 * /cashout stack layout — slide-from-bottom animation gives the cash-out flow
 * a modal feel, mirroring the /p2p stack.
 */
import { Stack } from 'expo-router';

import { useColors } from '@/lib/colors';

/** Cash-out (withdraw at agent) flow stack. */
export default function CashOutLayout() {
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
