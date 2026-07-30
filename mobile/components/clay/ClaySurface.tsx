/**
 * ClaySurface / ClayCard — the raised puffy clay surface primitive.
 *
 * A Tamagui `View` that measures itself and paints a Skia clay `Box` behind its
 * content (`ClayShape`): a clay fill + inner highlight/depth shadows + a soft
 * navy outer drop, giving true inflated-clay depth. Content paints on top on a
 * transparent background so the inner shadows stay visible. Before first layout
 * the view shows a plain rounded fill so there's no flash.
 *
 * Layout props (margin, width, flex, padding, …) pass straight through to the
 * underlying View, so screens use it as a drop-in card wrapper. The public
 * props are unchanged from the previous RN-shadow implementation.
 */
import { ComponentProps } from 'react';
import { View } from 'tamagui';

import { ClayShape, useClaySize } from './ClayShape';
import { clayRadius, claySurface } from './recipe';

interface ClaySurfaceProps extends ComponentProps<typeof View> {
  /** Shadow depth. `raised` (default) is the puffy card; `soft` is denser. */
  depth?: 'raised' | 'soft';
  /** Corner radius. Defaults to the medium clay radius. */
  radius?: number;
  /** Surface fill. Defaults to the raised clay off-white. */
  fill?: string;
  /** Kept for API compatibility (the Skia inner highlight replaces the sheen). */
  sheen?: boolean;
}

/** Raised clay surface. Use directly for bespoke cards, or `ClayCard`. */
export function ClaySurface({
  depth = 'raised',
  radius = clayRadius.md,
  fill = claySurface.raised,
  // `sheen` is accepted for backwards-compat but no longer used — the Skia
  // inner highlight now provides the top-left sheen. Destructured so it isn't
  // forwarded to the View.
  sheen: _sheen = true,
  children,
  style,
  ...rest
}: ClaySurfaceProps) {
  const [size, onLayout] = useClaySize();
  const drop = depth === 'raised' ? 'raised' : 'soft';
  return (
    <View
      onLayout={onLayout}
      borderRadius={radius}
      // Transparent once measured so the Skia fill + inner shadows show; a plain
      // rounded fill until then so there's no flash of unstyled content.
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
          variant="raised"
          drop={drop}
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
