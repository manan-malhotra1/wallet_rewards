/**
 * /settings — app settings (Sasai Pay).
 *
 * Navy gradient header + a clay body. Currently hosts a single control: the
 * Dark mode toggle, bound to the app-wide theme preference (lib/theme.ts).
 * Flipping it switches Tamagui's active theme + the status-bar style app-wide
 * (wired in app/_layout.tsx). Full dark styling of every screen is a separate
 * later effort — hence the "in beta" note under the toggle.
 */
import { Switch } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { GradientHeader } from '@/components/brand/GradientHeader';
import { HeaderBack } from '@/components/brand/HeaderBack';
import { ClaySurface } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { useThemePref } from '@/lib/theme';

/** Settings screen. */
export default function SettingsScreen() {
  const { pref, setPref } = useThemePref();
  const isDark = pref === 'dark';
  const colors = useColors();

  return (
    <View flex={1} backgroundColor={colors.screenBg}>
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <GradientHeader paddingBottom={24}>
          <HeaderBack title="Settings" />
          <Text
            fontFamily="PlusJakartaSans-Medium"
            fontSize={12.5}
            color="rgba(255,255,255,0.85)"
            marginTop={10}
          >
            Personalise how Sasai Pay looks and behaves.
          </Text>
        </GradientHeader>

        <YStack paddingHorizontal={18} paddingTop={18} gap={10}>
          <Text
            fontFamily="PlusJakartaSans-Bold"
            fontSize={12}
            color={colors.textMuted}
            textTransform="uppercase"
            letterSpacing={0.8}
            paddingHorizontal={4}
          >
            Appearance
          </Text>

          <ClaySurface depth="soft" radius={18} paddingHorizontal={16} paddingVertical={14}>
            <XStack alignItems="center" gap={12}>
              <View
                width={38}
                height={38}
                borderRadius={12}
                backgroundColor={colors.rim}
                alignItems="center"
                justifyContent="center"
              >
                <Ionicons name="moon" size={19} color={colors.navy} />
              </View>
              <YStack flex={1}>
                <Text fontFamily="PlusJakartaSans-Bold" fontSize={14.5} color={colors.text}>
                  Dark mode
                </Text>
                <Text fontFamily="PlusJakartaSans-Medium" fontSize={12} color={colors.textMuted}>
                  Use a darker colour scheme.
                </Text>
              </YStack>
              <Switch
                value={isDark}
                onValueChange={(next) => setPref(next ? 'dark' : 'light')}
                trackColor={{ false: '#c3d0de', true: colors.teal }}
                thumbColor={isDark ? colors.navy : '#ffffff'}
                ios_backgroundColor="#c3d0de"
                accessibilityRole="switch"
                accessibilityLabel="Dark mode"
              />
            </XStack>

            {/* Full dark styling of every screen is deferred — the toggle flips
                the Tamagui theme now, but hardcoded-color screens won't fully
                adapt until they're re-themed. Set expectations here. */}
            <Text
              fontFamily="PlusJakartaSans-Medium"
              fontSize={11.5}
              color={colors.textMuted}
              marginTop={12}
              lineHeight={16}
            >
              Dark theme is in beta — some screens are still being tuned.
            </Text>
          </ClaySurface>
        </YStack>
      </SafeAreaView>
    </View>
  );
}
