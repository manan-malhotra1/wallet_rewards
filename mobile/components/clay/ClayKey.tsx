/**
 * ClayKey — a tappable clay key for numeric keypads (amount pad, PIN pad).
 *
 * Raised clay tile at rest; on press it reads pushed-IN via the Skia `pressed`
 * variant (recessed inner shadows, no outer drop) and the tile nudges down 1px.
 * Because a key can be `flex` (width unknown until layout) it measures itself
 * and paints the Skia clay `Box` behind its content once sized. Children are
 * the glyph (a digit, "⌫", a biometric icon). The parent owns what the key
 * does — this only renders + reports the press. Public props are unchanged.
 */
import { Pressable } from 'react-native';
import { View } from 'tamagui';

import { ClayShape, useClaySize, useClayTokens } from './ClayShape';

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
  const [size, onLayout] = useClaySize();
  const tokens = useClayTokens();
  const keyFill = tokens.surface.raised;
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
          onLayout={onLayout}
          width={flex ? '100%' : width}
          height={height}
          borderRadius={radius}
          alignItems="center"
          justifyContent="center"
          backgroundColor={size ? 'transparent' : keyFill}
          style={{ transform: [{ translateY: pressed ? 1 : 0 }] }}
        >
          {size ? (
            <ClayShape
              width={size.w}
              height={size.h}
              radius={radius}
              fill={keyFill}
              variant={pressed ? 'pressed' : 'raised'}
              drop="soft"
            />
          ) : null}
          {children}
        </View>
      )}
    </Pressable>
  );
}
