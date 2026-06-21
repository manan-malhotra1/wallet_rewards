/**
 * Auth-flow layout. Headerless stack — each screen draws its own back chevron
 * and title. Animation defaults are fine; we explicitly disable the header so
 * the design language stays bare.
 */
import { Stack } from 'expo-router';

/** Stack wrapper for /auth/* routes. */
export default function AuthLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
