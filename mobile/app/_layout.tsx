/**
 * Root layout — wires every provider the app needs.
 *
 * Stack:
 *   - GestureHandlerRootView (required by react-native-gesture-handler)
 *   - SafeAreaProvider
 *   - TamaguiProvider (theme + tokens; selects light/dark from useColorScheme)
 *   - QueryClientProvider (TanStack Query, lazy-used in dispatch 2)
 *
 * Splash screen is held until Inter fonts load, then hidden. The visible
 * stack is a thin Expo-Router Stack with header off so each route owns its
 * own chrome.
 */
import { useEffect } from 'react';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useFonts } from 'expo-font';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { QueryClientProvider } from '@tanstack/react-query';
import { PortalProvider, TamaguiProvider } from 'tamagui';

import tamaguiConfig from '@/tamagui.config';
import { queryClient } from '@/lib/query';

// Hold the splash until fonts + first render are ready (~hundreds of ms).
SplashScreen.preventAutoHideAsync().catch(() => {
  /* Already hidden — fine. */
});

/**
 * Root provider tree. Hides the splash once fonts are loaded.
 *
 * Theme is locked to `light` for v0 — the brand assets and every screen's
 * colour choices were authored against a light surface. Dark-mode support
 * lands later once we audit every screen for contrast.
 */
export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    'Inter-Regular': require('../assets/fonts/Inter-Regular.ttf'),
    'Inter-Medium': require('../assets/fonts/Inter-Medium.ttf'),
    'Inter-SemiBold': require('../assets/fonts/Inter-SemiBold.ttf'),
    'Inter-Bold': require('../assets/fonts/Inter-Bold.ttf'),
  });

  useEffect(() => {
    if (fontsLoaded) {
      SplashScreen.hideAsync().catch(() => {
        /* No-op — already hidden. */
      });
    }
  }, [fontsLoaded]);

  // Don't render the tree until fonts are loaded — avoids a visible
  // font-swap from system → Inter on first paint.
  if (!fontsLoaded) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <TamaguiProvider config={tamaguiConfig} defaultTheme="light">
          {/* PortalProvider is required for Tamagui Sheet / Dialog /
              Popover to mount their content above the screen. The
              `shouldAddRootHost` flag registers the default portal host
              so consumers don't need to name it. */}
          <PortalProvider shouldAddRootHost>
            <QueryClientProvider client={queryClient}>
              <StatusBar style="dark" />
              <Stack screenOptions={{ headerShown: false }} />
            </QueryClientProvider>
          </PortalProvider>
        </TamaguiProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
