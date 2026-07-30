/**
 * ClayButton — the clay CTA primitive.
 *
 *   - `primary`  — a navy LinearGradient face, white label, strong drop shadow.
 *   - `neutral`  — a raised clay face, ink label, soft drop shadow.
 *
 * Pressed state reads as pushed-in: the shadow shrinks + pulls close, the face
 * nudges down 1px, and a faint downward dark sheen is overlaid. The gradient
 * faces carry their own `borderRadius` (not `overflow: 'hidden'`) so the drop
 * shadow survives on iOS. Logic stays with the caller — this is presentation.
 */
import { ActivityIndicator, Pressable } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Text, View } from 'tamagui';

import {
  claySurface,
  clayRimLight,
  elevation,
  highlightColors,
  highlightEnd,
  highlightLocations,
  highlightStart,
  insetShadeColors,
  insetShadeLocations,
  navyGradient,
  overlayFill,
  shadowPressed,
  shadowSoft,
  shadowStrong,
} from './recipe';

interface ClayButtonProps {
  /** Tap handler. Ignored while `disabled` or `loading`. */
  onPress?: () => void;
  disabled?: boolean;
  /** Swap the label for a spinner (keeps the button sized + tinted). */
  loading?: boolean;
  variant?: 'primary' | 'neutral';
  height?: number;
  radius?: number;
  /** Stretch to the parent width. Defaults to true. */
  fullWidth?: boolean;
  accessibilityLabel?: string;
  /** A string renders as the styled label; nodes render as-is (icon rows). */
  children: React.ReactNode;
}

/** Clay call-to-action button with a pressed-in state. */
export function ClayButton({
  onPress,
  disabled = false,
  loading = false,
  variant = 'primary',
  height = 54,
  radius = 16,
  fullWidth = true,
  accessibilityLabel,
  children,
}: ClayButtonProps) {
  const isPrimary = variant === 'primary';
  const inert = disabled || loading;
  return (
    <Pressable
      onPress={inert ? undefined : onPress}
      disabled={inert}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      style={{ width: fullWidth ? '100%' : undefined, opacity: disabled ? 0.5 : 1 }}
    >
      {({ pressed }) => {
        const shadow = pressed ? shadowPressed : isPrimary ? shadowStrong : shadowSoft;
        const elev = pressed ? elevation.pressed : isPrimary ? elevation.strong : elevation.soft;
        return (
          <View
            height={height}
            borderRadius={radius}
            alignItems="center"
            justifyContent="center"
            backgroundColor={isPrimary ? '#013a6b' : claySurface.raised}
            borderWidth={1}
            borderColor={isPrimary ? 'rgba(255,255,255,0.18)' : clayRimLight}
            {...shadow}
            style={{ elevation: elev, transform: [{ translateY: pressed ? 1 : 0 }] }}
          >
            <LinearGradient
              colors={isPrimary ? navyGradient : highlightColors}
              locations={isPrimary ? undefined : highlightLocations}
              start={isPrimary ? { x: 0, y: 0 } : highlightStart}
              end={isPrimary ? { x: 1, y: 1 } : highlightEnd}
              pointerEvents="none"
              style={overlayFill(radius)}
            />
            {pressed ? (
              <LinearGradient
                colors={insetShadeColors}
                locations={insetShadeLocations}
                start={{ x: 0, y: 0 }}
                end={{ x: 0, y: 1 }}
                pointerEvents="none"
                style={overlayFill(radius)}
              />
            ) : null}
            {loading ? (
              <ActivityIndicator color={isPrimary ? '#ffffff' : '#00508F'} />
            ) : typeof children === 'string' ? (
              <Text
                fontFamily="PlusJakartaSans-Bold"
                fontSize={16}
                color={isPrimary ? '#ffffff' : '#00508F'}
              >
                {children}
              </Text>
            ) : (
              children
            )}
          </View>
        );
      }}
    </Pressable>
  );
}
