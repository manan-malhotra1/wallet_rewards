/**
 * ClayKey — a tappable clay key for numeric keypads (amount pad, PIN pad).
 *
 * Raised clay tile at rest; on press it reads pushed-IN: the shadow collapses,
 * the tile nudges down 1px, the white sheen is dropped, and a downward dark
 * sheen is overlaid. Children are the glyph (a digit, "⌫", a biometric icon).
 * The parent owns what the key does — this only renders + reports the press.
 */
import { Pressable } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { View } from 'tamagui';

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
  overlayFill,
  shadowPressed,
  shadowSoft,
} from './recipe';

interface ClayKeyProps {
  onPress?: () => void;
  disabled?: boolean;
  /** Render fully transparent + inert (keeps grid alignment for empty slots). */
  hidden?: boolean;
  /** Fill the available row width (flex:1) instead of a fixed `width`. */
  flex?: boolean;
  width?: number;
  height?: number;
  radius?: number;
  accessibilityLabel?: string;
  children: React.ReactNode;
}

/** A single raised/pressed clay keypad key. */
export function ClayKey({
  onPress,
  disabled = false,
  hidden = false,
  flex = false,
  width,
  height = 56,
  radius = 18,
  accessibilityLabel,
  children,
}: ClayKeyProps) {
  const inert = disabled || hidden;
  return (
    <Pressable
      onPress={inert ? undefined : onPress}
      disabled={inert}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      style={{ opacity: hidden ? 0 : 1, flex: flex ? 1 : undefined }}
    >
      {({ pressed }) => (
        <View
          width={flex ? '100%' : width}
          height={height}
          borderRadius={radius}
          alignItems="center"
          justifyContent="center"
          backgroundColor={claySurface.raised}
          borderWidth={1}
          borderColor={pressed ? claySurface.inset : clayRimLight}
          {...(pressed ? shadowPressed : shadowSoft)}
          style={{
            elevation: pressed ? elevation.pressed : elevation.soft,
            transform: [{ translateY: pressed ? 1 : 0 }],
          }}
        >
          {pressed ? (
            <LinearGradient
              colors={insetShadeColors}
              locations={insetShadeLocations}
              start={{ x: 0, y: 0 }}
              end={{ x: 0, y: 1 }}
              pointerEvents="none"
              style={overlayFill(radius)}
            />
          ) : (
            <LinearGradient
              colors={highlightColors}
              locations={highlightLocations}
              start={highlightStart}
              end={highlightEnd}
              pointerEvents="none"
              style={overlayFill(radius)}
            />
          )}
          {children}
        </View>
      )}
    </Pressable>
  );
}
