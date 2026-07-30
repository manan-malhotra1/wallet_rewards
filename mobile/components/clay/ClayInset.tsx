/**
 * ClayInset — a recessed (pushed-in) clay surface for fields + displays.
 *
 * Used where content should read carved into the clay rather than floating on
 * it: the big amount display, input fills, sunken value chips. Approximates an
 * inset shadow (which RN can't render without Skia) with a darker top/left rim
 * + a lighter bottom/right rim, plus a downward dark sheen overlaid from the
 * top. No outer drop shadow — that would make it read raised.
 */
import { ComponentProps } from 'react';
import { LinearGradient } from 'expo-linear-gradient';
import { View } from 'tamagui';

import {
  clayRadius,
  claySurface,
  insetShadeColors,
  insetShadeLocations,
  overlayFill,
} from './recipe';

interface ClayInsetProps extends ComponentProps<typeof View> {
  radius?: number;
  /** Surface fill. Defaults to the recessed clay inset color. */
  fill?: string;
}

/** Recessed clay surface. */
export function ClayInset({
  radius = clayRadius.md,
  fill = claySurface.inset,
  children,
  style,
  ...rest
}: ClayInsetProps) {
  return (
    <View
      backgroundColor={fill}
      borderRadius={radius}
      borderWidth={1}
      borderTopColor="rgba(1,46,84,0.12)"
      borderLeftColor="rgba(1,46,84,0.07)"
      borderRightColor="rgba(255,255,255,0.6)"
      borderBottomColor="rgba(255,255,255,0.7)"
      style={style}
      {...rest}
    >
      <LinearGradient
        colors={insetShadeColors}
        locations={insetShadeLocations}
        start={{ x: 0, y: 0 }}
        end={{ x: 0, y: 1 }}
        pointerEvents="none"
        style={overlayFill(radius)}
      />
      {children}
    </View>
  );
}
