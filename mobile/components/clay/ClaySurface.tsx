/**
 * ClaySurface / ClayCard — the raised puffy clay surface primitive.
 *
 * A single Tamagui `View` that carries the clay recipe: a clay fill, a big
 * rounded corner, the navy drop shadow (iOS shadow props + Android elevation),
 * a hairline light rim, and a rounded white highlight sheen overlaid top-left.
 * The overlay is a `LinearGradient` given the same `borderRadius` so its
 * corners clip to the surface WITHOUT `overflow: 'hidden'` — which would clip
 * the drop shadow on iOS. Children paint above the sheen (later in JSX).
 *
 * Layout props (margin, width, flex, padding, …) pass straight through to the
 * underlying View, so screens use it as a drop-in card wrapper.
 */
import { ComponentProps } from 'react';
import { LinearGradient } from 'expo-linear-gradient';
import { View } from 'tamagui';

import {
  clayRadius,
  claySurface,
  clayRimLight,
  elevation,
  highlightColors,
  highlightEnd,
  highlightLocations,
  highlightStart,
  overlayFill,
  shadowRaised,
  shadowSoft,
} from './recipe';

interface ClaySurfaceProps extends ComponentProps<typeof View> {
  /** Shadow depth. `raised` (default) is the puffy card; `soft` is denser. */
  depth?: 'raised' | 'soft';
  /** Corner radius. Defaults to the medium clay radius (24). */
  radius?: number;
  /** Surface fill. Defaults to the raised clay off-white. */
  fill?: string;
  /** Show the top-left white highlight sheen. Defaults to true. */
  sheen?: boolean;
}

/** Raised clay surface. Use directly for bespoke cards, or `ClayCard`. */
export function ClaySurface({
  depth = 'raised',
  radius = clayRadius.md,
  fill = claySurface.raised,
  sheen = true,
  children,
  style,
  ...rest
}: ClaySurfaceProps) {
  const shadow = depth === 'raised' ? shadowRaised : shadowSoft;
  const elev = depth === 'raised' ? elevation.raised : elevation.soft;
  return (
    <View
      backgroundColor={fill}
      borderRadius={radius}
      borderWidth={1}
      borderColor={clayRimLight}
      {...shadow}
      style={[{ elevation: elev }, style]}
      {...rest}
    >
      {sheen ? (
        <LinearGradient
          colors={highlightColors}
          locations={highlightLocations}
          start={highlightStart}
          end={highlightEnd}
          pointerEvents="none"
          style={overlayFill(radius)}
        />
      ) : null}
      {children}
    </View>
  );
}

/** Raised clay card — `ClaySurface` with comfortable card padding. */
export function ClayCard(props: ClaySurfaceProps) {
  return <ClaySurface padding={18} {...props} />;
}
