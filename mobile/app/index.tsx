/**
 * Launch route — redirects to /auth/phone or /home based on cached session.
 *
 * We don't validate the token against the backend on launch — that would
 * delay first paint and double the network calls on every open. Instead
 * we trust the cached token until an authenticated request returns 401,
 * which the storage layer treats as a sign to clear and re-auth.
 */
import { Redirect } from 'expo-router';
import { View } from 'tamagui';

import { useSession } from '@/lib/auth';

/** Auth-gated launch redirect. */
export default function Index() {
  const { loading, signedIn } = useSession();
  if (loading) {
    // Render nothing until we know — splash already covers this.
    return <View flex={1} backgroundColor="#ccd8e8" />;
  }
  return signedIn ? <Redirect href="/home" /> : <Redirect href="/auth/phone" />;
}
