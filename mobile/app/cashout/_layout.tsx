/**
 * /cashout stack layout — slide-from-bottom animation gives the cash-out flow
 * a modal feel, mirroring the /p2p stack.
 */
import { Stack } from 'expo-router';

/** Cash-out (withdraw at agent) flow stack. */
export default function CashOutLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        animation: 'slide_from_bottom',
        contentStyle: { backgroundColor: '#ccd8e8' },
      }}
    />
  );
}
