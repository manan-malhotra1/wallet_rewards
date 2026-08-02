/**
 * ClayPill — a small rounded pill with a teal clay face.
 *
 * Used for the teal accents (points pill, "verified" badge, quick chips). It
 * paints a Skia clay `Box` behind its content: a teal gradient face, the raised
 * inner highlight/depth shadows and a soft outer drop. Presentational only —
 * wrap it in a Pressable at the call site if it needs to be tappable. Public
 * props are unchanged.
 */
import { ComponentProps } from 'react';
import { View } from 'tamagui';

import { ClayShape, useClaySize, useClayTokens } from './ClayShape';

interface ClayPillProps extends ComponentProps<typeof View> {
  /** Corner radius. Defaults to a fully-rounded pill. */
  radius?: number;
  /** Gradient stops for the face. Defaults to the brand teal gradient. */
  colors?: readonly [string, string, ...string[]];
}

/** Teal (by default) gradient clay pill. */
export function ClayPill({
  radius = 999,
  colors,
  children,
  style,
  paddingHorizontal = 12,
  paddingVertical = 6,
  ...rest
}: ClayPillProps) {
  const [size, onLayout] = useClaySize();
  const tokens = useClayTokens();
  // Default to the active mode's teal gradient; explicit `colors` win.
  const faceColors = colors ?? tokens.gradients.teal;
  // A fully-rounded pill: clamp the Skia corner radius to half the shortest
  // side so the rounded box matches the CSS `borderRadius: 999` capsule.
  const skiaRadius = size ? Math.min(radius, Math.min(size.w, size.h) / 2) : radius;
  return (
    <View
      onLayout={onLayout}
      borderRadius={radius}
      paddingHorizontal={paddingHorizontal}
      paddingVertical={paddingVertical}
      backgroundColor={size ? 'transparent' : faceColors[0]}
      style={style}
      {...rest}
    >
      {size ? (
        <ClayShape
          width={size.w}
          height={size.h}
          radius={skiaRadius}
          fill={faceColors[0]}
          variant="raised"
          drop="soft"
          gradient={faceColors}
        />
      ) : null}
      {children}
    </View>
  );
}
