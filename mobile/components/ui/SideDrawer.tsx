/**
 * SideDrawer — slide-from-left side menu, opened from the home avatar.
 *
 * Shown when the user taps their avatar / name on the home screen. Hosts
 * the account summary (initials, name, masked phone) and the Sign out
 * CTA. Tapping the dim overlay outside the panel dismisses the drawer.
 *
 * Implemented with React Native's built-in Modal + Animated translateX
 * to avoid the Tamagui Sheet / PortalProvider dependency that bit us on
 * the bottom-sheet flow earlier. The panel is 280px wide; the rest of
 * the screen is dimmed at 45% opacity.
 *
 * Future: this is the natural slot for "Profile", "Settings",
 * "Security", "Help", "Switch wallet", and "About". They're not wired
 * yet — for the demo the only working action is Sign out.
 */
import { useEffect, useRef } from 'react';
import { Animated, Dimensions, Modal, Pressable } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';

import { SasaiPayLogo } from '@/components/brand/SasaiPayLogo';
import { maskPhone } from '@/lib/format';

const PANEL_WIDTH = 280;

interface Props {
  /** Whether the drawer is visible. */
  open: boolean;
  /** Called when the user dismisses (overlay tap or hardware back). */
  onClose: () => void;
  /** Called when the user taps Sign out. Parent owns the actual flow. */
  onSignOut: () => void;
  /** Display name. Falls back to "Sasai user" if null/empty. */
  name: string | null | undefined;
  /** E.164 phone (masked at render time). */
  phone: string | null | undefined;
  /** 2-letter avatar initials. */
  initials: string;
  /** Set true while the sign-out request is in flight. */
  signingOut?: boolean;
}

/** Side drawer with account summary + sign out. */
export function SideDrawer({
  open,
  onClose,
  onSignOut,
  name,
  phone,
  initials,
  signingOut = false,
}: Props) {
  const insets = useSafeAreaInsets();
  const x = useRef(new Animated.Value(-PANEL_WIDTH)).current;
  const dim = useRef(new Animated.Value(0)).current;

  // Slide-in / slide-out animation whenever `open` flips.
  useEffect(() => {
    Animated.parallel([
      Animated.timing(x, {
        toValue: open ? 0 : -PANEL_WIDTH,
        duration: 240,
        useNativeDriver: true,
      }),
      Animated.timing(dim, {
        toValue: open ? 1 : 0,
        duration: 240,
        useNativeDriver: true,
      }),
    ]).start();
  }, [open, x, dim]);

  return (
    <Modal
      animationType="none"
      transparent
      visible={open}
      onRequestClose={onClose}
      statusBarTranslucent
    >
      {/* Dim overlay — tap to dismiss. Pointer-events flip lets the panel
          remain interactive even while the overlay is animating. */}
      <Pressable
        onPress={onClose}
        accessibilityRole="button"
        accessibilityLabel="Close menu"
        style={{ flex: 1 }}
      >
        <Animated.View
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: 0,
            right: 0,
            backgroundColor: 'rgba(12,27,42,0.45)',
            opacity: dim,
          }}
        />
      </Pressable>

      {/* Panel — animated translateX from -PANEL_WIDTH to 0. */}
      <Animated.View
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: 0,
          width: PANEL_WIDTH,
          transform: [{ translateX: x }],
        }}
      >
        <View
          flex={1}
          backgroundColor="#eef3f9"
          paddingTop={insets.top + 12}
          paddingBottom={insets.bottom + 12}
          paddingHorizontal={20}
        >
          {/* Brand chrome */}
          <SasaiPayLogo width={110} payColor="navy" />

          {/* User summary */}
          <YStack alignItems="flex-start" gap={4} marginTop={28}>
            <View
              width={56}
              height={56}
              borderRadius={28}
              backgroundColor="#50C0D0"
              alignItems="center"
              justifyContent="center"
            >
              <Text
                fontFamily="PlusJakartaSans-Bold"
                fontSize={20}
                color="#013a6b"
              >
                {initials}
              </Text>
            </View>
            <Text
              fontFamily="PlusJakartaSans-ExtraBold"
              fontSize={18}
              color="#0c1b2a"
              marginTop={10}
            >
              {name || 'Sasai user'}
            </Text>
            <Text
              fontFamily="PlusJakartaSans-Medium"
              fontSize={13}
              color="#6a7888"
            >
              {phone ? maskPhone(phone) : '—'}
            </Text>
          </YStack>

          {/* Menu items. Only Sign out is wired today; the rest are
              labelled but inert so the surface looks complete. */}
          <YStack marginTop={32} gap={4}>
            {[
              { icon: '👤', label: 'Profile', disabled: true },
              { icon: '🔒', label: 'Security', disabled: true },
              { icon: '🛟', label: 'Help & support', disabled: true },
              { icon: 'ℹ️', label: 'About Sasai Pay', disabled: true },
            ].map((item) => (
              <View
                key={item.label}
                paddingVertical={12}
                paddingHorizontal={4}
                flexDirection="row"
                alignItems="center"
                gap={12}
                opacity={item.disabled ? 0.45 : 1}
              >
                <Text fontSize={18}>{item.icon}</Text>
                <Text
                  fontFamily="PlusJakartaSans-SemiBold"
                  fontSize={14.5}
                  color="#0c1b2a"
                >
                  {item.label}
                </Text>
              </View>
            ))}
          </YStack>

          <View flex={1} />

          {/* Sign out — actual wired action. */}
          <Pressable
            onPress={signingOut ? undefined : onSignOut}
            disabled={signingOut}
            accessibilityRole="button"
            accessibilityLabel="Sign out"
            style={({ pressed }) => ({ opacity: pressed && !signingOut ? 0.7 : 1 })}
          >
            <XStack
              alignItems="center"
              gap={10}
              paddingVertical={12}
              paddingHorizontal={4}
              borderTopWidth={1}
              borderTopColor="rgba(1,46,84,0.08)"
            >
              <Text fontSize={18}>↪️</Text>
              <Text
                fontFamily="PlusJakartaSans-Bold"
                fontSize={14.5}
                color="#c0392b"
              >
                {signingOut ? 'Signing out…' : 'Sign out'}
              </Text>
            </XStack>
          </Pressable>
        </View>
      </Animated.View>
    </Modal>
  );
}
