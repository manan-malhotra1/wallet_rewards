/**
 * /p2p stack layout — slide-from-bottom animation gives the flow a modal feel
 * even though it's a regular stack (no native modal presentation chrome).
 */
import { Stack } from 'expo-router';

/** Send-money flow stack. */
export default function P2PLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        animation: 'slide_from_bottom',
        contentStyle: { backgroundColor: '#FFFFFF' },
      }}
    />
  );
}
