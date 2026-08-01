/**
 * /airtime stack layout — mirrors the /p2p flow's slide-from-bottom feel so
 * the airtime top-up reads as a focused task launched from home.
 */
import { Stack } from 'expo-router';

/** Airtime top-up flow stack. */
export default function AirtimeLayout() {
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
