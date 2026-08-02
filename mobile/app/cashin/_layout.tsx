/**
 * /cashin stack layout — slide-from-bottom animation gives the cash-in flow
 * a modal feel, mirroring the /cashout stack.
 */
import { Stack } from 'expo-router';

import { useColors } from '@/lib/colors';

/** Cash-in (agent funds a customer) flow stack. */
export default function CashInLayout() {
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
