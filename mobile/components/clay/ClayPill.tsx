/**
 * ClayPill — a small rounded pill with a teal LinearGradient face.
 *
 * Used for the teal accents (points pill, "verified" badge, quick chips). It's
 * a fully-rounded clay chip: teal gradient face, soft drop shadow, a hairline
 * light rim, and a rounded highlight sheen. Presentational only — wrap it in a
 * Pressable at the call site if it needs to be tappable.
 */
import { ComponentProps } from 'react';
import { LinearGradient } from 'expo-linear-gradient';
import { View } from 'tamagui';

import {
  clayRimLight,
  elevation,
  highlightColors,
  highlightEnd,
  highlightLocations,
  highlightStart,
  overlayFill,
  shadowSoft,
  tealGradient,
} from './recipe';

interface ClayPillProps extends ComponentProps<typeof View> {
  /** Corner radius. Defaults to a fully-rounded pill. */
  radius?: number;
  /** Gradient stops for the face. Defaults to the brand teal gradient. */
  colors?: readonly [string, string, ...string[]];
}

/** Teal (by default) gradient clay pill. */
export function ClayPill({
  radius = 999,
  colors = tealGradient,
  children,
  style,
  paddingHorizontal = 12,
  paddingVertical = 6,
  ...rest
}: ClayPillProps) {
  return (
    <View
      borderRadius={radius}
      paddingHorizontal={paddingHorizontal}
      paddingVertical={paddingVertical}
      backgroundColor="#2EB6C8"
      borderWidth={1}
      borderColor={clayRimLight}
      {...shadowSoft}
      style={[{ elevation: elevation.soft }, style]}
      {...rest}
    >
      <LinearGradient
        colors={colors}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        pointerEvents="none"
        style={overlayFill(radius)}
      />
      <LinearGradient
        colors={highlightColors}
        locations={highlightLocations}
        start={highlightStart}
        end={highlightEnd}
        pointerEvents="none"
        style={overlayFill(radius)}
      />
      {children}
    </View>
  );
}
