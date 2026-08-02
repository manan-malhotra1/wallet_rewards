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
import { ThemeProvider, useThemePref } from '@/lib/theme';

// Hold the splash until fonts + first render are ready (~hundreds of ms).
SplashScreen.preventAutoHideAsync().catch(() => {
  /* Already hidden — fine. */
});

/**
 * Themed provider tree — reads the user's theme preference and drives both
 * Tamagui's `defaultTheme` and the status-bar style from it.
 *
 * Split out from `RootLayout` so it can call `useThemePref()`, which requires
 * a `ThemeProvider` ancestor (wired in `RootLayout`). Dark preference flips
 * Tamagui to its `dark` theme and the status bar to light glyphs; light does
 * the inverse. Full dark re-theming of every screen is a separate later effort
 * — Tamagui-themed surfaces adapt now, hardcoded-color screens are pending.
 */
function ThemedApp() {
  const { pref } = useThemePref();
  const isDark = pref === 'dark';

  return (
    <TamaguiProvider config={tamaguiConfig} defaultTheme={pref}>
      {/* PortalProvider is required for Tamagui Sheet / Dialog /
          Popover to mount their content above the screen. The
          `shouldAddRootHost` flag registers the default portal host
          so consumers don't need to name it. */}
      <PortalProvider shouldAddRootHost>
        <QueryClientProvider client={queryClient}>
          {/* Dark theme → light status-bar glyphs, and vice versa. */}
          <StatusBar style={isDark ? 'light' : 'dark'} />
          <Stack screenOptions={{ headerShown: false }} />
        </QueryClientProvider>
      </PortalProvider>
    </TamaguiProvider>
  );
}

/**
 * Root provider tree. Hides the splash once fonts are loaded.
 *
 * `ThemeProvider` sits ABOVE `TamaguiProvider` (inside `ThemedApp`) so the
 * user's persisted light/dark preference selects the Tamagui theme. The app
 * still defaults to `light`; dark mode is opt-in from Settings and its full
 * per-screen re-theming lands later.
 */
export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    'PlusJakartaSans-Regular': require('../assets/fonts/PlusJakartaSans-Regular.ttf'),
    'PlusJakartaSans-Medium': require('../assets/fonts/PlusJakartaSans-Medium.ttf'),
    'PlusJakartaSans-SemiBold': require('../assets/fonts/PlusJakartaSans-SemiBold.ttf'),
    'PlusJakartaSans-Bold': require('../assets/fonts/PlusJakartaSans-Bold.ttf'),
    'PlusJakartaSans-ExtraBold': require('../assets/fonts/PlusJakartaSans-ExtraBold.ttf'),
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
        <ThemeProvider>
          <ThemedApp />
        </ThemeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
