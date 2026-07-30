/**
 * ClayInset — a recessed (pushed-in) clay surface for fields + displays.
 *
 * Used where content should read carved into the clay rather than floating on
 * it: the big amount display, input fills, sunken value chips. It paints a Skia
 * clay `Box` behind its content with the `inset` variant — a strong navy inner
 * shadow top-left + a faint inner highlight bottom-right and NO outer drop — so
 * the surface reads genuinely recessed. Public props are unchanged.
 */
import { ComponentProps } from 'react';
import { View } from 'tamagui';

import { ClayShape, useClaySize } from './ClayShape';
import { clayRadius, claySurface } from './recipe';

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
  const [size, onLayout] = useClaySize();
  return (
    <View
      onLayout={onLayout}
      borderRadius={radius}
      backgroundColor={size ? 'transparent' : fill}
      style={style}
      {...rest}
    >
      {size ? (
        <ClayShape
          width={size.w}
          height={size.h}
          radius={radius}
          fill={fill}
          variant="inset"
        />
      ) : null}
      {children}
    </View>
  );
}
